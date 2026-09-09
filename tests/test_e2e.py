"""
端到端集成测试：启动 serve.py，模拟 ReAct 循环，验证 REST API + 短期记忆闭环

策略：
  - monkey-patch tools.TOOLS_MAP，用 fake_tool 返回预置字符串
  - monkey-patch react_manual 的 client.chat.completions，模拟 LLM 一步步返回 Thought/Action/Observation
  - 起 uvicorn 跑在 8765 端口（后台）
  - 走完"首轮 + 追问一轮"完整流程
"""

import os
import sys
import json
import time
import threading
import subprocess
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

# ── 临时数据目录隔离 ──────────────────────────────────────────────────────────
_TMP = Path(tempfile.mkdtemp(prefix="react_e2e_"))
os.environ["DASHSCOPE_API_KEY"] = "sk-fake-for-test"
os.environ["DEEPSEEK_API_KEY"]  = "sk-fake-for-test"

# 替换记忆目录
import memory
memory.MEMORY_DIR = _TMP / "memory"
memory.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
# 替换 vectorstore（避免真实 FAISS 加载）
fake_vs = _TMP / "vectorstore"
fake_vs.mkdir(parents=True, exist_ok=True)
import tools
tools.VECTORSTORE_DIR = fake_vs


# ── Mock 工具 ────────────────────────────────────────────────────────────────
def mock_company_lookup(name):
    code = tools.COMPANY_MAP.get(name, "000000")
    return f"{name} 的股票代码为 {code}"

def mock_rag_search(query, top_k=5):
    return f"[mock] 关于 '{query}' 的年报内容：毛利率91.96%（2023）"

def mock_calculator(expr):
    return "16.17"

def mock_financial_indicator(symbol):
    return f"股票代码: {symbol}，2023年毛利率: 91.96"

def mock_stock_price(symbol, start_date, end_date):
    return f"股票代码: {symbol}，涨跌幅: +5.23%"

tools.TOOLS_MAP = {
    "rag_search":          mock_rag_search,
    "company_lookup":      mock_company_lookup,
    "calculator":          mock_calculator,
    "financial_indicator": mock_financial_indicator,
    "stock_price":         mock_stock_price,
}
# 跳过真实 _load_rag
tools._load_rag = lambda: None


# ── Mock LLM：模拟"茅台五粮液毛利率对比"的 5 步 ReAct ─────────────────────────
from openai import OpenAI

SCRIPT = [
    # 第1轮 q1: 茅台五粮液毛利率对比
    [
        # Step 1: lookup 茅台
        "Thought: 先查茅台的股票代码\nAction: company_lookup\nAction Input: {\"name\": \"贵州茅台\"}",
        # Step 2: lookup 五粮液
        "Thought: 再查五粮液\nAction: company_lookup\nAction Input: {\"name\": \"五粮液\"}",
        # Step 3: 茅台财务
        "Thought: 查茅台财务指标\nAction: financial_indicator\nAction Input: {\"symbol\": \"600519\"}",
        # Step 4: 五粮液财务
        "Thought: 查五粮液财务指标\nAction: financial_indicator\nAction Input: {\"symbol\": \"000858\"}",
        # Step 5: 计算
        "Thought: 算差值\nAction: calculator\nAction Input: {\"expr\": \"91.96 - 75.79\"}",
        # Final
        "Thought: 已有结论\nFinal Answer: 茅台 91.96% > 五粮液 75.79%，高出 16.17 个百分点",
    ],
    # 第2轮 q2: 那另一家呢？ → 改写为"五粮液呢？"
    [
        "Thought: 上一轮已经分析过茅台，本轮要查五粮液，先查代码\nAction: company_lookup\nAction Input: {\"name\": \"五粮液\"}",
        "Thought: 查五粮液财务指标\nAction: financial_indicator\nAction Input: {\"symbol\": \"000858\"}",
        "Thought: 可以给出答案\nFinal Answer: 五粮液 2023 年毛利率为 75.79%，比茅台低 16.17 个百分点",
    ],
]

class FakeMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

class FakeChoice:
    def __init__(self, content, tool_calls=None, finish_reason="stop"):
        self.message = FakeMessage(content, tool_calls)
        self.finish_reason = finish_reason

class FakeResponse:
    def __init__(self, content, tool_calls=None, finish_reason="stop"):
        self.choices = [FakeChoice(content, tool_calls, finish_reason)]

class FakeCompletions:
    """模拟 manual 版的 client.chat.completions.create"""
    def __init__(self):
        self.call_count = 0
        self.scenario_index = 0
        self.scripts = SCRIPT

    def create(self, **kwargs):
        # 选择当前轮次的脚本
        script = self.scripts[min(self.scenario_index, len(self.scripts) - 1)]
        idx = min(self.call_count, len(script) - 1)
        content = script[idx]
        self.call_count += 1
        # 脚本用完后返回 Final Answer（让循环正常结束）
        if self.call_count > len(script):
            content = "Thought: 兜底\nFinal Answer: 测试结束"
        return FakeResponse(content)


class FakeToolCall:
    def __init__(self, name, args, call_id):
        self.function = type("F", (), {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        })()
        self.id = call_id

class FakeFCMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

class FakeFCChoice:
    def __init__(self, message, finish_reason):
        self.message = message
        self.finish_reason = finish_reason

class FakeFCResponse:
    def __init__(self, message, finish_reason):
        self.choices = [FakeFCChoice(message, finish_reason)]

class FakeFCCompletions:
    """模拟 function_calling 版的 create（无 Thought 文本）"""
    def __init__(self):
        self.scenario_index = 0
        self.scripts = SCRIPT

    def create(self, **kwargs):
        # 判断模式：manual 版带 stop=["Observation:"], fc 版带 tools=[...]
        is_fc = "tools" in kwargs
        script = self.scripts[min(self.scenario_index, len(self.scripts) - 1)]

        if not hasattr(self, "_step"):
            self._step = 0
        idx = min(self._step, len(script) - 1)
        text = script[idx]
        self._step += 1

        if not is_fc:
            return FakeResponse(text)

        # FC 版：解析 text 决定返回 tool_calls 还是 final
        # 兜底：脚本用完后给一个 final
        if self._step > 10:
            return FakeFCResponse(FakeFCMessage(content="测试结束"), finish_reason="stop")
        if "Final Answer:" in text:
            answer = text.split("Final Answer:", 1)[1].strip()
            return FakeFCResponse(FakeFCMessage(content=answer), finish_reason="stop")
        else:
            # 解析 Action / Action Input
            import re
            action = re.search(r"Action:\s*(\w+)", text).group(1)
            args_raw = re.search(r"Action Input:\s*(\{.+?\})", text, re.DOTALL).group(1)
            args = json.loads(args_raw)
            tc = FakeToolCall(action, args, f"call_{idx}")
            return FakeFCResponse(FakeFCMessage(tool_calls=[tc]), finish_reason="tool_calls")

# 安装 mock（每次新会话重置 step）
_fake_manual = FakeCompletions()
_fake_fc     = FakeFCCompletions()

def make_manual_client():
    c = FakeCompletions()
    c.scenario_index = _fake_manual.scenario_index
    _fake_manual.scenario_index += 1
    return c

def make_fc_client():
    c = FakeFCCompletions()
    c.scenario_index = _fake_fc.scenario_index
    _fake_fc.scenario_index += 1
    c._step = 0
    return c

# 替换两个模块的 client
import react_manual
import react_function_calling

class StubClient:
    def __init__(self, is_fc=False):
        self.is_fc = is_fc
        # 关键：缓存 completions 对象，否则每次访问 .chat 都会新建 scenario
        self._completions = make_fc_client() if is_fc else make_manual_client()
    @property
    def chat(self):
        return type("C", (), {"completions": self._completions})()

react_manual.client = StubClient(is_fc=False)
react_function_calling.client = StubClient(is_fc=True)


# ── 启动 serve.py（同进程，用 uvicorn 在线程里跑） ────────────────────────────
import uvicorn
from serve import app

PORT = 8765
config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", lifespan="on")
server = uvicorn.Server(config)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

# 等待就绪
import urllib.request
ready = False
for _ in range(40):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1)
        ready = True
        break
    except Exception:
        time.sleep(0.25)
if not ready:
    print("[server] start failed")
    sys.exit(1)
print(f"[server] ready on :{PORT}")


# ── 端到端：用 requests 发请求，解析 SSE ──────────────────────────────────────
import urllib.request

def post_sse(path, payload):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    events = []
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    except Exception as e:
        print(f"[err] {e}")
    return events


def get_json(path):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}").read())


def delete(path):
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method="DELETE")
    urllib.request.urlopen(req).read()


# ══════════════════════════════════════════════════════════════════════════════
# 测试流程
# ══════════════════════════════════════════════════════════════════════════════
print("\n=== E2E: 创建会话 → 首轮 → 追问 → 验证记忆 ===\n")

# 1. 创建会话
r = get_json("/sessions")
all_sids = [s["session_id"] for s in r["sessions"]]
new_sid = f"sess_e2e_{int(time.time())}"
# 通过 add_turn 写一个空 session（也可通过 POST /sessions 创建但需要直接调用 memory）
from memory import ShortTermMemory
ShortTermMemory(new_sid)
print(f"[1] 创建会话 {new_sid}")

# 2. 首轮
print(f"\n[2] 首轮提问...")
events = post_sse(f"/sessions/{new_sid}/query/manual", {
    "question": "贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？",
    "max_steps": 10,
})
types = [e.get("type") for e in events]
print(f"  收到事件: {types}")
has_action = any(t == "action" for t in types)
has_final  = any(t == "final"  for t in types)
has_snap   = any(t == "memory_snapshot" for t in types)
print(f"  action={has_action} final={has_final} snapshot={has_snap}")

# 3. 追问（"那另一家呢？"）
print(f"\n[3] 追问 '那另一家呢？'...")
events = post_sse(f"/sessions/{new_sid}/query/manual", {
    "question": "那另一家呢？",
    "max_steps": 10,
})
types = [e.get("type") for e in events]
print(f"  收到事件: {types}")
rewrites = [e for e in events if e.get("type") == "memory_rewrite"]
print(f"  改写横幅: {rewrites}")

# 4. 检查记忆
print(f"\n[4] 检查会话记忆...")
mem_data = get_json(f"/sessions/{new_sid}")
print(f"  turns 数: {len(mem_data['turns'])}")
for i, t in enumerate(mem_data["turns"], 1):
    rewritten_flag = "✓被改写" if t.get("was_rewritten") else "原样"
    entities = "、".join(e["name"] for e in t.get("entities", []))
    print(f"  Turn {i} [{rewritten_flag}]: {t['user_question']}")
    if t.get("rewritten_question"):
        print(f"    改写后: {t['rewritten_question']}")
    print(f"    实体: [{entities}]")
    print(f"    指标: {t.get('metric_focus')}")
    print(f"    工具: {t.get('tools_used')}")

# 5. 列出所有会话
print(f"\n[5] 列出所有会话...")
all_sess = get_json("/sessions")
print(f"  共 {len(all_sess['sessions'])} 个会话")

# 6. 清空会话
print(f"\n[6] 清空会话...")
delete(f"/sessions/{new_sid}")
mem_data = get_json(f"/sessions/{new_sid}")
print(f"  清空后 turns 数: {len(mem_data['turns'])}")

# 7. Function Calling 版端到端
print(f"\n[7] Function Calling 版端到端...")
_fc_fake_sid = "sess_e2e_fc"
ShortTermMemory(_fc_fake_sid)
events = post_sse(f"/sessions/{_fc_fake_sid}/query/fc", {
    "question": "茅台和五粮液2023年毛利率差多少？",
    "max_steps": 10,
})
types = [e.get("type") for e in events]
print(f"  FC 版事件: {types}")
mem_data = get_json(f"/sessions/{_fc_fake_sid}")
print(f"  FC 版 turn 数: {len(mem_data['turns'])}, 实体: {[e['name'] for e in mem_data['turns'][0]['entities']]}")

# ── 收尾 ──────────────────────────────────────────────────────────────────────
server.should_exit = True
thread.join(timeout=5)
shutil.rmtree(_TMP, ignore_errors=True)
print("\n[done] E2E 测试完成")