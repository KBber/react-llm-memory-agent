"""
memory.py 模块单元测试 —— 覆盖所有改写分支、实体追踪、持久化

运行：
  cd react_financial_agent
  python tests/test_memory.py
"""

import sys
import json
import shutil
import tempfile
from pathlib import Path

# 把 src 加到 import 路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

import memory
from memory import (
    ShortTermMemory, Entity, Turn,
    extract_entities, detect_metric_focus,
    rewrite_follow_up,
    collect_entities_from_steps,
    _extract_year,
)

# ── 临时目录隔离（不污染真实 data/memory）───────────────────────────────────
_tmpdir = tempfile.mkdtemp()
memory.MEMORY_DIR = Path(_tmpdir)
print(f"[setup] MEMORY_DIR = {memory.MEMORY_DIR}\n")


# ── 工具函数：打印一行带颜色的 PASS/FAIL ─────────────────────────────────────
PASS = "\033[32m✓ PASS\033[0m"
FAIL = "\033[31m✗ FAIL\033[0m"
results = []

def check(name, cond, detail=""):
    if cond:
        print(f"{PASS} {name}")
        results.append((name, True, detail))
    else:
        print(f"{FAIL} {name}  {detail}")
        results.append((name, False, detail))


# ══════════════════════════════════════════════════════════════════════════════
# 1. 实体抽取
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 1. 实体抽取 extract_entities ──")

ents = extract_entities("贵州茅台和五粮液2023年毛利率对比")
check("两公司全名都被识别", len(ents) == 2 and {e.name for e in ents} == {"贵州茅台", "五粮液"})

ents = extract_entities("宁德时代与中国平安")
check("复杂公司名也能识别", {e.name for e in ents} == {"宁德时代", "中国平安"})

ents = extract_entities("茅台")
check("短别名映射到正确代码", len(ents) == 1 and ents[0].code == "600519")

ents = extract_entities("人工智能")
check("未登录公司返回空", ents == [])

ents = extract_entities("贵州茅台2023年毛利率")
m = next((e for e in ents if e.name == "贵州茅台"), None)
check("实体携带 metric", m and m.metric == "毛利率", f"got metric={m.metric if m else None}")
check("实体携带 year",   m and m.year == "2023年",     f"got year={m.year if m else None}")


# ══════════════════════════════════════════════════════════════════════════════
# 2. 年份抽取
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 2. 年份抽取 _extract_year ──")
check("YYYY年",  _extract_year("2023年的营收") == "2023年")
check("YYYY-YYYY", _extract_year("2021-2023年趋势") == "2021-2023")
check("YYYY到YYYY", _extract_year("2021到2023年") == "2021-2023")
check("裸 YYYY", _extract_year("2023") == "2023")
check("无年份", _extract_year("昨天") is None)


# ══════════════════════════════════════════════════════════════════════════════
# 3. 指标焦点识别
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 3. 指标焦点 detect_metric_focus ──")
check("毛利率", detect_metric_focus("茅台2023年毛利率") == "毛利率")
check("ROE",    detect_metric_focus("ROE多少") == "ROE")
check("风险",  detect_metric_focus("年报中提到哪些风险") == "风险")
check("无指标 → None", detect_metric_focus("你好") is None)


# ══════════════════════════════════════════════════════════════════════════════
# 4. 指代消解 —— contrast 分支
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 4. 指代消解 (contrast 分支) ──")

# 场景 A：上一轮 [茅台, 五粮液] → "那另一家呢" → 应改为 五粮液
mem = ShortTermMemory("test_a")
mem.turns = []   # 不污染
mem.add_turn(
    user_question="贵州茅台和五粮液2023年毛利率哪家高？",
    entities=[Entity(name="贵州茅台", code="600519"), Entity(name="五粮液", code="000858")],
    metric_focus="毛利率",
    answer="茅台更高",
)
rw = rewrite_follow_up("那另一家呢？", mem)
check("A1: 触发改写", rw["rewritten"])
check("A2: 策略=contrast", rw["strategy"] == "contrast")
check("A3: 改写为五粮液", "五粮液" in rw["question"], f"got: {rw['question']}")

# 场景 B：本轮明确提到茅台 → 不触发（用户已指定实体）
mem = ShortTermMemory("test_b")
mem.turns = []
mem.add_turn(
    user_question="贵州茅台和五粮液2023年毛利率哪家高？",
    entities=[Entity(name="贵州茅台", code="600519"), Entity(name="五粮液", code="000858")],
    metric_focus="毛利率",
    answer="...",
)
rw = rewrite_follow_up("那茅台呢？", mem)
check("B: 茅台已在本轮提到 → 不改写", not rw["rewritten"])

# 场景 C：上一轮 3 家，本轮提到 1 家，应挑未提及的
mem = ShortTermMemory("test_c")
mem.turns = []
mem.add_turn(
    user_question="茅台、五粮液、宁德时代谁的ROE高？",
    entities=[
        Entity(name="贵州茅台", code="600519"),
        Entity(name="五粮液",   code="000858"),
        Entity(name="宁德时代", code="300750"),
    ],
    metric_focus="ROE",
)
# 本轮提到茅台，应改写为"五粮液"或"宁德时代"中的最后一个未提及的
rw = rewrite_follow_up("那另一家呢？茅台不算", mem)
check("C1: 触发改写", rw["rewritten"])
check("C2: target 不在本轮已提到的列表", rw.get("target_entity") and rw["target_entity"].code != "600519",
      f"target={rw.get('target_entity')}")


# ══════════════════════════════════════════════════════════════════════════════
# 5. 指代消解 —— repeat 分支
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 5. 指代消解 (repeat 分支) ──")

mem = ShortTermMemory("test_d")
mem.turns = []
mem.add_turn(
    user_question="茅台2023年毛利率是多少？",
    entities=[Entity(name="贵州茅台", code="600519")],
    metric_focus="毛利率",
)
rw = rewrite_follow_up("再来一次", mem)
check("D1: 触发改写", rw["rewritten"])
check("D2: 策略=repeat", rw["strategy"] == "repeat")
check("D3: question 含沿用提示", "毛利率" in rw["question"], f"got: {rw['question']}")


# ══════════════════════════════════════════════════════════════════════════════
# 6. 无触发词 → 不改写
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 6. 无触发词 ──")

mem = ShortTermMemory("test_e")
mem.turns = []
mem.add_turn(
    user_question="茅台2023年毛利率",
    entities=[Entity(name="贵州茅台", code="600519")],
    metric_focus="毛利率",
)
rw = rewrite_follow_up("宁德时代呢？", mem)
check("E: 不触发改写", not rw["rewritten"])
check("E: question 保持原样", rw["question"] == "宁德时代呢？")


# ══════════════════════════════════════════════════════════════════════════════
# 7. 无上一轮 → 不改写
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 7. 无上一轮 ──")
mem = ShortTermMemory("test_f")
mem.turns = []
rw = rewrite_follow_up("那另一家呢？", mem)
check("F: 无记忆时不改写", not rw["rewritten"])


# ══════════════════════════════════════════════════════════════════════════════
# 8. 从工具步进结果里收集实体
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 8. collect_entities_from_steps ──")

steps = [
    {"type": "action", "action": "company_lookup",    "action_input": {"name": "贵州茅台"}},
    {"type": "action", "action": "company_lookup",    "action_input": {"name": "五粮液"}},
    {"type": "action", "action": "financial_indicator","action_input": {"symbol": "600519"}},
    {"type": "action", "action": "financial_indicator","action_input": {"symbol": "000858"}},
    {"type": "action", "action": "calculator",        "action_input": {"expr": "91-75"}},
    {"type": "final",  "answer": "差16个百分点"},
]
ents = collect_entities_from_steps(steps)
codes = {e.code for e in ents}
check("G1: 抽到两个代码", codes == {"600519", "000858"}, f"got {codes}")
check("G2: 无重复",      len(ents) == 2)


# ══════════════════════════════════════════════════════════════════════════════
# 9. 持久化往返
# ══════════════════════════════════════════════════════════════════════════════
print("\n── 9. 持久化往返 ──")

mem1 = ShortTermMemory("test_persist")
mem1.turns = []
mem1.add_turn(
    user_question="茅台2023年毛利率",
    entities=[Entity(name="贵州茅台", code="600519")],
    metric_focus="毛利率",
    answer="91.96%",
    tools_used=["financial_indicator"],
)

mem2 = ShortTermMemory("test_persist")   # 重新加载
check("H1: 重新加载后 turn 数一致", len(mem2.turns) == 1)
check("H2: turn 内容一致", mem2.turns[0].user_question == "茅台2023年毛利率")
check("H3: entity 一致",  mem2.turns[0].entities[0].code == "600519")
check("H4: answer 一致",  mem2.turns[0].answer == "91.96%")

# 验证 JSON 文件存在
json_path = memory.MEMORY_DIR / "test_persist.json"
check("H5: JSON 文件落盘", json_path.exists())
with open(json_path, encoding="utf-8") as f:
    data = json.load(f)
check("H6: JSON 顶层有 session_id", data.get("session_id") == "test_persist")
check("H7: JSON 顶层有 turns",      isinstance(data.get("turns"), list) and len(data["turns"]) == 1)


# ══════════════════════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════════════════════
total  = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print(f"\n{'='*60}")
print(f"memory.py 单元测试：{passed}/{total} 通过")
print('='*60)

# 清理
shutil.rmtree(_tmpdir, ignore_errors=True)

sys.exit(0 if passed == total else 1)