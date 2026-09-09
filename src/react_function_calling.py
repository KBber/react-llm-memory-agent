"""
Function Calling API 版 ReAct Agent

教学重点：
  1. 与手写版对比：框架帮你处理格式解析，但 Thought 过程在内部不可见
  2. tool_choice="auto" 让模型自己决定调用哪个工具或直接回答
  3. finish_reason 判断：tool_calls 表示继续调用，stop 表示给出最终答案
  4. 相同工具集，相同问题，对比两种实现的稳定性和步骤数

使用方式：
  python react_function_calling.py
  python react_function_calling.py --question "茅台近一年股价涨跌幅如何？"
  python react_function_calling.py --question "..." --max_steps 8

依赖：
  pip install openai faiss-cpu sentence-transformers akshare
  export DASHSCOPE_API_KEY="sk-xxx"
"""

import os
import json
import time
import logging
import argparse
from typing import Generator

from openai import OpenAI

from memory import (
    ShortTermMemory,
    rewrite_follow_up,
    extract_entities,
    collect_entities_from_steps,
    detect_metric_focus,
)

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# client = OpenAI(
#     api_key=os.getenv("DASHSCOPE_API_KEY"),
#     base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
# )
# MODEL = os.getenv("AGENT_MODEL", "qwen-max")
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)
MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")

FC_SYSTEM_PROMPT = """你是一个专业的A股金融分析助手。
规则：
- 调用 financial_indicator 或 stock_price 之前，必须先用 company_lookup 获取股票代码
- 数字计算必须使用 calculator 工具，不能心算
- Final Answer 必须引用具体数据来源
- 如果没有合适工具能回答，直接说明原因
"""


def run(
    question: str,
    max_steps: int = 10,
    session_id: str | None = None,
    memory: ShortTermMemory | None = None,
) -> Generator[dict, None, None]:
    """
    执行 Function Calling 版 ReAct 循环，yield 每一步结构化结果

    格式与 react_manual.run() 保持一致，便于 evaluate.py 统一对比
    """
    from tools import TOOLS_MAP, TOOLS_SCHEMA

    # ── 短期记忆接入 ────────────────────────────────────────────────────────
    if memory is None and session_id is not None:
        memory = ShortTermMemory(session_id)

    rewrite_info: dict = {"rewritten": False}
    actual_question = question
    if memory is not None:
        rewrite_info = rewrite_follow_up(question, memory)
        if rewrite_info["rewritten"]:
            actual_question = rewrite_info["question"]
            yield {
                "type":          "memory_rewrite",
                "raw_question":  question,
                "question":      actual_question,
                "strategy":      rewrite_info["strategy"],
                "reason":        rewrite_info["reason"],
            }

    memory_context = ""
    if memory is not None and memory.turns:
        last = memory.last_turn
        if last and last.entities:
            entity_names = "、".join(e.name for e in last.entities if e.name)
            metric = last.metric_focus or "无明确指标"
            memory_context = (
                f"\n\n[上一轮对话记忆]\n"
                f"用户上一轮问过：{last.user_question}\n"
                f"涉及的实体：{entity_names}\n"
                f"关注的指标：{metric}\n"
                f"如果当前问题包含指代（如'那另一家呢''那个呢''也看看'），请沿用上述上下文。"
            )

    messages = [
        {"role": "system", "content": FC_SYSTEM_PROMPT + memory_context},
        {"role": "user",   "content": actual_question},
    ]

    collected_steps: list[dict] = []
    final_answer: str | None = None

    for step in range(1, max_steps + 1):
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0,
        )
        msg    = response.choices[0].message
        reason = response.choices[0].finish_reason

        # 模型决定直接回答（无工具调用）
        if reason == "stop" or not msg.tool_calls:
            step_result = {
                "step":   step,
                "type":   "final",
                "thought": "",
                "answer": msg.content or "（模型返回空内容）",
            }
            yield step_result
            final_answer = step_result["answer"]
            collected_steps.append(step_result)
            break

        # 模型请求调用工具
        messages.append(msg)

        for tool_call in msg.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            tool_fn = TOOLS_MAP.get(tool_name)
            if tool_fn is None:
                observation = f"未知工具 '{tool_name}'"
            else:
                try:
                    observation = tool_fn(**tool_args)
                except TypeError as e:
                    observation = f"工具参数错误: {e}"

            step_result = {
                "step":         step,
                "type":         "action",
                "thought":      "",   # Function Calling 版 Thought 在模型内部，不可见
                "action":       tool_name,
                "action_input": tool_args,
                "observation":  str(observation),
            }
            yield step_result
            collected_steps.append(step_result)

            messages.append({
                "role":         "tool",
                "tool_call_id": tool_call.id,
                "content":      str(observation),
            })

    else:
        yield {
            "step":   max_steps + 1,
            "type":   "max_steps",
            "answer": f"已达最大步数 {max_steps}，未能得出最终答案",
        }

    # ── 写入短期记忆 ─────────────────────────────────────────────────────────
    if memory is not None:
        try:
            entities = collect_entities_from_steps(collected_steps)
            if not entities:
                entities = extract_entities(actual_question)
            tools_used = [s["action"] for s in collected_steps if s.get("type") == "action"]
            memory.add_turn(
                user_question=question,
                rewritten_question=actual_question if rewrite_info.get("rewritten") else None,
                was_rewritten=bool(rewrite_info.get("rewritten")),
                rewrite_reason=rewrite_info.get("reason"),
                answer=final_answer,
                entities=entities,
                metric_focus=detect_metric_focus(actual_question),
                tools_used=tools_used,
            )
        except Exception as e:
            logger.warning(f"写入短期记忆失败: {e}")


# ── CLI 打印（复用 react_manual 的彩色输出） ───────────────────────────────────

COLORS = {
    "thought": "\033[36m",
    "action":  "\033[33m",
    "obs":     "\033[32m",
    "final":   "\033[35m",
    "error":   "\033[31m",
    "reset":   "\033[0m",
}

def _c(color: str, text: str) -> str:
    return f"{COLORS[color]}{text}{COLORS['reset']}"


def run_and_print(
    question: str,
    max_steps: int = 10,
    session_id: str | None = None,
    memory: ShortTermMemory | None = None,
):
    print(f"\n{'='*60}")
    print(f"问题: {question}")
    if session_id:
        print(f"会话: {session_id}")
    print(f"模型: {MODEL}  实现: Function Calling")
    print('='*60)

    start = time.time()

    for step_data in run(
        question,
        max_steps=max_steps,
        session_id=session_id,
        memory=memory,
    ):
        stype = step_data["type"]

        if stype == "memory_rewrite":
            print(_c("action", f"\n🧠 记忆改写: '{step_data['raw_question']}' → '{step_data['question']}'"))
            print(_c("action", f"   策略: {step_data['strategy']}  理由: {step_data['reason']}"))

        elif stype == "action":
            print(f"\n[Step {step_data['step']}]")
            # Thought 在 FC 版不可见，显示提示
            print(_c("thought", "🧠 Thought: （模型内部推理，Function Calling 版不可见）"))
            print(_c("action",  f"🔧 Action:  {step_data['action']}"))
            print(_c("action",  f"   Input:   {json.dumps(step_data['action_input'], ensure_ascii=False)}"))
            print(_c("obs",     f"👁  Obs:     {step_data['observation'][:300]}"))

        elif stype == "final":
            elapsed = time.time() - start
            print(f"\n{'─'*60}")
            print(_c("final", f"\n✅ Final Answer:\n{step_data['answer']}"))
            print(f"\n共 {step_data['step']} 步，耗时 {elapsed:.1f}s")

        elif stype in ("error", "max_steps"):
            print(_c("error", f"\n⚠️  {step_data.get('answer', '')}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question",  default="贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？")
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--session",   default=None, help="会话ID，传入后开启短期记忆")
    parser.add_argument("--reset",     action="store_true", help="清空指定会话的历史记忆")
    args = parser.parse_args()

    mem = None
    if args.session:
        from memory import ShortTermMemory
        mem = ShortTermMemory(args.session)
        if args.reset:
            mem.turns = []
            mem.save()
            print(f"已清空会话 {args.session} 的记忆")

    run_and_print(args.question, args.max_steps, session_id=args.session, memory=mem)
