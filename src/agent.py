"""
统一入口：切换手写版 / Function Calling 版 ReAct Agent

使用方式：
  python agent.py
  python agent.py --mode manual   --question "茅台2023年毛利率是多少？"
  python agent.py --mode fc       --question "五粮液近一年股价涨跌幅？"
  python agent.py --mode manual   --question "..." --max_steps 8

多轮对话（启用短期记忆）：
  python agent.py --session demo --question "茅台和五粮液2023毛利率哪家高？"
  python agent.py --session demo --question "那另一家呢？"
  python agent.py --session demo --question "宁德时代呢？" --reset

环境变量：
  DASHSCOPE_API_KEY  必填
  AGENT_MODEL        默认 qwen-max，可换 deepseek-v3 等
"""

import os
import argparse

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

DEFAULT_QUESTION = "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ReAct Financial Agent")
    parser.add_argument(
        "--mode", choices=["manual", "fc"], default="manual",
        help="manual=手写Prompt解析版  fc=Function Calling版",
    )
    parser.add_argument("--question",  default=DEFAULT_QUESTION)
    parser.add_argument("--max_steps", type=int, default=10)
    parser.add_argument("--session",   default=None, help="会话ID，开启短期记忆")
    parser.add_argument("--reset",     action="store_true", help="清空当前会话的历史")
    args = parser.parse_args()

    if args.mode == "manual":
        from react_manual import run_and_print
    else:
        from react_function_calling import run_and_print

    mem = None
    if args.session:
        from memory import ShortTermMemory
        mem = ShortTermMemory(args.session)
        if args.reset:
            mem.turns = []
            mem.save()
            print(f"已清空会话 {args.session} 的记忆")

    run_and_print(args.question, args.max_steps, session_id=args.session, memory=mem)
