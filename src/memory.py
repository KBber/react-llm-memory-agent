"""
短期记忆 + 实体追踪 + 指代消解

教学目标：
  1. 演示"短期记忆"的最小实现 —— JSON 文件 + 会话隔离
  2. 演示"实体追踪" —— Agent 知道自己上一轮提过哪些公司
  3. 演示"指代消解" —— 用户问"那另一家呢"时，模型能理解指代对象

使用方式：
  from memory import ShortTermMemory, rewrite_follow_up

  mem = ShortTermMemory("sess_abc")
  rewrite = rewrite_follow_up("那另一家呢？", mem)
  if rewrite["rewritten"]:
      question = rewrite["question"]   # 自动替换为上一轮未提及的实体
  mem.add_turn(user_q=..., answer=..., entities=[...], ...)

数据结构（每个 session 一个 JSON 文件）：
  data/memory/<session_id>.json
  {
    "session_id": ...,
    "turns": [
        {
          "turn_id": 1,
          "user_question": "...",
          "rewritten_question": "...",   # 改写后真正发给 Agent 的问题
          "was_rewritten": false,
          "answer": "...",
          "entities": [{"name": "...", "code": "...", "metric": "...", "year": "..."}],
          "metric_focus": "毛利率",
          "tools_used": ["..."],
          "timestamp": "..."
        }
    ]
  }
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

# ── 路径配置 ──────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent
MEMORY_DIR = BASE_DIR / "data" / "memory"
MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ── 公司字典（与 tools.py 保持同步） ──────────────────────────────────────────
COMPANY_MAP = {
    "贵州茅台": "600519",
    "茅台":     "600519",
    "五粮液":   "000858",
    "宁德时代": "300750",
    "中国平安": "601318",
    "平安":     "601318",
    "海康威视": "002415",
    "海康":     "002415",
}
NAME_BY_CODE = {v: k for k, v in COMPANY_MAP.items()}

# ── 指标词典（同一问句里的"焦点指标"，沿用到改写后的问题）────────────────────
METRIC_KEYWORDS = [
    "毛利率", "净利率", "营收", "营业收入", "净利润", "归母净利润",
    "ROE", "净资产收益率", "资产负债率", "每股收益", "市盈率",
    "涨跌幅", "股价", "风险因素", "风险", "战略", "研发投入",
]

# ── 指代消解触发词 ────────────────────────────────────────────────────────────
# 第一组：对比类，问"另一家""另一个"——必须挑未提及的实体替换
CONTRAST_TRIGGERS = ["那另一家", "那另一个", "那家", "另一个", "另外一家", "另一家呢"]
# 第二组：重复类，沿用同一指标重问
REPEAT_TRIGGERS = ["那呢", "这个呢", "也一样", "同样", "再来一次", "重复"]
# 时间延续词
TIME_DELTA_TRIGGERS = ["近一年", "去年", "前年", "前一年", "上一季度"]


# ══════════════════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Entity:
    """一轮对话里提到的实体（公司 + 关注的指标 + 时间窗）"""
    name:   str               # "贵州茅台"
    code:   str | None = None # "600519"
    metric: str | None = None # "毛利率"
    year:   str | None = None # "2023"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Entity":
        return cls(
            name=d.get("name", ""),
            code=d.get("code"),
            metric=d.get("metric"),
            year=d.get("year"),
        )


@dataclass
class Turn:
    """一轮对话的完整记录"""
    turn_id:           int
    user_question:     str
    rewritten_question: str | None = None
    was_rewritten:     bool = False
    rewrite_reason:    str | None = None
    answer:            str | None = None
    entities:          list[Entity] = field(default_factory=list)
    metric_focus:      str | None = None
    tools_used:        list[str] = field(default_factory=list)
    timestamp:         float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entities"] = [e.to_dict() for e in self.entities]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Turn":
        return cls(
            turn_id=d["turn_id"],
            user_question=d["user_question"],
            rewritten_question=d.get("rewritten_question"),
            was_rewritten=d.get("was_rewritten", False),
            rewrite_reason=d.get("rewrite_reason"),
            answer=d.get("answer"),
            entities=[Entity.from_dict(e) for e in d.get("entities", [])],
            metric_focus=d.get("metric_focus"),
            tools_used=d.get("tools_used", []),
            timestamp=d.get("timestamp", time.time()),
        )


# ══════════════════════════════════════════════════════════════════════════════
# 记忆读写
# ══════════════════════════════════════════════════════════════════════════════

class ShortTermMemory:
    """单会话的短期记忆，JSON 文件持久化"""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or f"sess_{uuid.uuid4().hex[:8]}"
        self.path = MEMORY_DIR / f"{self.session_id}.json"
        self.turns: list[Turn] = []
        self._load()

    # ── I/O ──────────────────────────────────────────────────────────────────
    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    data = json.load(f)
                self.turns = [Turn.from_dict(t) for t in data.get("turns", [])]
            except (json.JSONDecodeError, KeyError):
                self.turns = []

    def save(self):
        data = {
            "session_id": self.session_id,
            "updated_at": time.time(),
            "turns": [t.to_dict() for t in self.turns],
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 读 ────────────────────────────────────────────────────────────────────
    @property
    def last_turn(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    def last_entities(self) -> list[Entity]:
        if not self.turns:
            return []
        return list(self.turns[-1].entities)

    def last_metric_focus(self) -> str | None:
        return self.turns[-1].metric_focus if self.turns else None

    def mentioned_codes_this_turn(self, current_question: str) -> set[str]:
        """从当前问题里识别出已经明确提到的公司代码"""
        codes: set[str] = set()
        for name, code in COMPANY_MAP.items():
            if name in current_question:
                codes.add(code)
        # 也直接识别6位股票代码
        for code in re.findall(r"\b[036]\d{5}\b", current_question):
            codes.add(code)
        return codes

    # ── 写 ────────────────────────────────────────────────────────────────────
    def add_turn(
        self,
        user_question: str,
        entities: list[Entity],
        metric_focus: str | None = None,
        tools_used: list[str] | None = None,
        answer: str | None = None,
        rewritten_question: str | None = None,
        was_rewritten: bool = False,
        rewrite_reason: str | None = None,
    ) -> Turn:
        turn = Turn(
            turn_id=len(self.turns) + 1,
            user_question=user_question,
            rewritten_question=rewritten_question,
            was_rewritten=was_rewritten,
            rewrite_reason=rewrite_reason,
            answer=answer,
            entities=entities,
            metric_focus=metric_focus,
            tools_used=tools_used or [],
        )
        self.turns.append(turn)
        self.save()
        return turn


# ══════════════════════════════════════════════════════════════════════════════
# 实体抽取（从用户问题里识别公司 + 指标 + 年份）
# ══════════════════════════════════════════════════════════════════════════════

def extract_entities(question: str) -> list[Entity]:
    """从问题中识别公司实体，匹配最长的公司名优先"""
    found: list[Entity] = []
    seen_codes: set[str] = set()
    # 按公司名长度倒序，避免"茅台"在"贵州茅台"里被先匹配
    sorted_names = sorted(COMPANY_MAP.keys(), key=lambda x: -len(x))
    for name in sorted_names:
        if name in question and COMPANY_MAP[name] not in seen_codes:
            metric = next((m for m in METRIC_KEYWORDS if m in question), None)
            year = _extract_year(question)
            found.append(Entity(name=name, code=COMPANY_MAP[name], metric=metric, year=year))
            seen_codes.add(COMPANY_MAP[name])
    return found


def _extract_year(question: str) -> str | None:
    """识别问题里的年份字符串：2023年 / 2023 / 2021-2023 / 2021到2023"""
    m = re.search(r"(20\d{2})\s*[-到~]\s*(20\d{2})", question)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"20\d{2}\s*年", question)
    if m:
        return m.group(0).replace(" ", "")
    m = re.search(r"\b(20\d{2})\b", question)
    if m:
        return m.group(1)
    return None


def detect_metric_focus(question: str) -> str | None:
    """识别问题中的核心指标，沿用到附加提问"""
    for m in METRIC_KEYWORDS:
        if m in question:
            return m
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 指代消解：附加提问改写
# ══════════════════════════════════════════════════════════════════════════════

def rewrite_follow_up(
    question: str,
    memory: ShortTermMemory,
) -> dict[str, Any]:
    """
    判定并改写附加提问。

    返回：
      {
        "rewritten": bool,        # 是否被改写
        "question": str,          # 改写后的问题（如果未改写则为原问题）
        "reason":  str | None,    # 改写理由，便于调试
        "strategy": str | None,   # 改写策略名：contrast / repeat
      }
    """
    last = memory.last_turn
    if last is None or not last.entities:
        # 没有上一轮或上一轮没提到实体，无法消解
        return {"rewritten": False, "question": question, "reason": None, "strategy": None}

    q = question.strip()
    last_entities = last.entities
    metric_focus  = last.metric_focus or detect_metric_focus(last.user_question)

    # ── 1. 对比类触发：找上一轮所有实体里"未在本轮被提到"的，挑一个替换进去 ──
    is_contrast = any(trigger in q for trigger in CONTRAST_TRIGGERS)
    if is_contrast:
        mentioned_codes = memory.mentioned_codes_this_turn(q)
        # 上一轮里没在本轮出现的实体（顺序保持与上一轮一致）
        unmentioned = [e for e in last_entities if e.code not in mentioned_codes]

        if unmentioned:
            # 选"上一轮里最后一个未被本轮提及的"——
            # 例如上一轮 [茅台, 五粮液]、本轮只字未提，"那另一家"自然指代五粮液。
            # 若本轮已提及其中一个，则选另一个。
            target = unmentioned[-1]
            rewritten = _swap_entity(q, target, last_entities, metric_focus)
            return {
                "rewritten": True,
                "question":  rewritten,
                "reason":    f"对比类指代 → 替换为 {target.name}",
                "strategy":  "contrast",
                "target_entity": target,
            }

    # ── 2. 重复类触发：用户可能想说"那就再来一次 / 一样" —— 沿用 metric 提示 ──
    is_repeat = any(trigger in q for trigger in REPEAT_TRIGGERS)
    if is_repeat and metric_focus and last_entities:
        # 不强改写，但在 question 前加一句提示，告诉 LLM 沿用上一轮指标
        # 这样 LLM 自己能从工具历史里推断出实体
        rewritten = f"{q}（沿用上一轮关注的指标：{metric_focus}）"
        return {
            "rewritten": True,
            "question":  rewritten,
            "reason":    f"重复类指代 → 沿用指标 {metric_focus}",
            "strategy":  "repeat",
        }

    # ── 3. 没有任何触发词 ──
    return {"rewritten": False, "question": question, "reason": None, "strategy": None}


def _swap_entity(
    question: str,
    target: Entity,
    last_entities: list[Entity],
    metric_focus: str | None,
) -> str:
    """
    把附加提问里的"那另一家""那家"等代词替换成 target.name，
    并在末尾补充 metric 让问题自洽。
    """
    q = question
    # 移除触发词（保留句子的语气词）
    for trigger in CONTRAST_TRIGGERS:
        q = q.replace(trigger, "")

    q = q.strip("，。.？? ")
    if not q:
        # 整句就一个触发词，重写成完整问句
        if metric_focus:
            return f"{target.name}的{metric_focus}是多少？"
        return f"{target.name}的情况怎么样？"

    # 保留句子的语气，补上具体主体
    if not q.endswith("？") and not q.endswith("?"):
        q += "？"
    return f"{target.name}{q}"


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数：从 Agent 步进结果里提取元数据
# ══════════════════════════════════════════════════════════════════════════════

def collect_entities_from_steps(steps: list[dict], company_lookup_arg: str | None = None) -> list[Entity]:
    """
    从 ReAct 步骤里提取本轮用到的所有公司实体。
    两种来源：
      1. company_lookup 的 action_input.name
      2. financial_indicator / stock_price 的 action_input.symbol
    """
    entities: list[Entity] = []
    seen: set[str] = set()

    for step in steps:
        if step.get("type") != "action":
            continue
        action = step.get("action", "")
        args   = step.get("action_input", {}) or {}

        if action == "company_lookup":
            name = args.get("name", "")
            if name and name in COMPANY_MAP and COMPANY_MAP[name] not in seen:
                entities.append(Entity(name=name, code=COMPANY_MAP[name]))
                seen.add(COMPANY_MAP[name])
        elif action in ("financial_indicator", "stock_price"):
            symbol = str(args.get("symbol", "")).strip()
            if symbol and symbol not in seen:
                # 反查公司名
                name = NAME_BY_CODE.get(symbol, symbol)
                entities.append(Entity(name=name, code=symbol))
                seen.add(symbol)

    return entities


def extract_metric_from_question(question: str, observation: str | None = None) -> str | None:
    """从问题或observation里识别指标焦点（优先用问题）"""
    m = detect_metric_focus(question)
    if m:
        return m
    if observation:
        return detect_metric_focus(observation[:500])
    return None


# ══════════════════════════════════════════════════════════════════════════════
# CLI 调试
# ══════════════════════════════════════════════════════════════════════════════

def _demo():
    """手动跑一轮演示：上一轮问茅台五粮液毛利率，本轮问'那另一家呢'"""
    print("=" * 60)
    print("memory.py 自检 demo")
    print("=" * 60)

    mem = ShortTermMemory("demo")
    mem.turns = []  # 清空旧数据

    # 第一轮
    q1 = "贵州茅台和五粮液2023年的毛利率哪家更高？"
    e1 = extract_entities(q1)
    print(f"\n[Turn 1] {q1}")
    print(f"  实体: {[e.name for e in e1]}")
    print(f"  指标: {detect_metric_focus(q1)}")
    mem.add_turn(
        user_question=q1,
        entities=e1,
        metric_focus=detect_metric_focus(q1),
        answer="茅台毛利率91.96% > 五粮液75.79%，高出16.17个百分点",
        tools_used=["company_lookup", "financial_indicator", "calculator"],
    )

    # 第二轮：附加提问
    q2 = "那另一家呢？"
    rw = rewrite_follow_up(q2, mem)
    print(f"\n[Turn 2 raw]    {q2}")
    print(f"[Turn 2 rewritten] {rw['question']}")
    print(f"  改写: {rw['rewritten']}  策略: {rw['strategy']}  理由: {rw['reason']}")

    # 第三轮：再来一个测试
    q3 = "那宁德时代呢？"
    rw3 = rewrite_follow_up(q3, mem)
    print(f"\n[Turn 3 raw]      {q3}")
    print(f"[Turn 3 rewritten] {rw3['question']}")
    print(f"  改写: {rw3['rewritten']}  策略: {rw3['strategy']}")


if __name__ == "__main__":
    _demo()