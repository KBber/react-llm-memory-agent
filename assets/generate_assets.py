"""
生成简历项目演示用的 SVG 资源：
  1. demo-comparison.svg —— "无记忆 vs 有记忆"对比图
  2. architecture.svg    —— 架构图
  3. rewrite-flow.svg    —— 指代消解流程图

运行：
  python assets/generate_assets.py
"""

from pathlib import Path

OUT = Path(__file__).parent

# ── 调色板（GitHub 深色背景兼容） ─────────────────────────────────────────────
BG     = "#0f1117"
PANEL  = "#1a1d27"
BORDER = "#2d3148"
TEXT   = "#e2e8f0"
DIM    = "#64748b"
ACCENT = "#a78bfa"   # 紫 - 记忆
BLUE   = "#38bdf8"   # 蓝 - Thought
YELLOW = "#fbbf24"   # 黄 - Action
GREEN  = "#34d399"   # 绿 - Observation
RED    = "#f87171"   # 红 - 错误


def svg_header(w, h, title=""):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif">
<rect width="{w}" height="{h}" fill="{BG}"/>
"""


# ══════════════════════════════════════════════════════════════════════════════
# 1. demo-comparison.svg —— 左：无记忆，右：有记忆
# ══════════════════════════════════════════════════════════════════════════════

def make_comparison():
    W, H = 1200, 560
    s = svg_header(W, H, "对比图")

    # 标题
    s += f"""
<text x="{W/2}" y="42" text-anchor="middle" font-size="24" font-weight="700" fill="{TEXT}">ReAct Agent 多轮对话对比</text>
<text x="{W/2}" y="68" text-anchor="middle" font-size="14" fill="{DIM}">第二轮提问："那另一家呢？"</text>
"""

    # ── 左边：无记忆 Agent ──
    LX = 40
    s += f"""
<rect x="{LX}" y="100" width="540" height="420" rx="12" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
<text x="{LX+20}" y="130" font-size="16" font-weight="700" fill="{RED}">❌  无记忆的 Agent</text>
<text x="{LX+20}" y="152" font-size="12" fill="{DIM}">传统 ReAct，每轮独立，无上下文</text>
"""

    # Turn 1
    s += f"""
<rect x="{LX+20}" y="180" width="500" height="50" rx="8" fill="{BG}" stroke="{BORDER}"/>
<text x="{LX+34}" y="202" font-size="11" fill="{DIM}">第 1 轮</text>
<text x="{LX+34}" y="220" font-size="13" fill="{TEXT}">茅台和五粮液2023年毛利率哪家高？</text>
"""

    # Turn 2
    s += f"""
<rect x="{LX+20}" y="248" width="500" height="50" rx="8" fill="{BG}" stroke="{BORDER}"/>
<text x="{LX+34}" y="270" font-size="11" fill="{DIM}">第 2 轮</text>
<text x="{LX+34}" y="288" font-size="13" fill="{TEXT}">那另一家呢？</text>
"""

    # 错误响应
    s += f"""
<rect x="{LX+20}" y="316" width="500" height="170" rx="8" fill="{BG}" stroke="{RED}" stroke-width="1.5"/>
<text x="{LX+34}" y="340" font-size="11" font-weight="700" fill="{RED}">⚠️  Agent 响应</text>
<text x="{LX+34}" y="362" font-size="12" fill="{TEXT}">"另一家"是哪家？请明确公司名。</text>
<text x="{LX+34}" y="384" font-size="12" fill="{DIM}">（要求用户重新表述，</text>
<text x="{LX+34}" y="400" font-size="12" fill="{DIM}">   工具调用失败 0/1，浪费一次）</text>
<text x="{LX+34}" y="438" font-size="11" font-weight="700" fill="{RED}">结果：体验差 / 需澄清</text>
"""

    # ── 右边：有记忆 Agent（本项目） ──
    RX = 620
    s += f"""
<rect x="{RX}" y="100" width="540" height="420" rx="12" fill="{PANEL}" stroke="{ACCENT}" stroke-width="2"/>
<text x="{RX+20}" y="130" font-size="16" font-weight="700" fill="{ACCENT}">✅  本项目：带记忆的 Agent</text>
<text x="{RX+20}" y="152" font-size="12" fill="{DIM}">短期记忆 + 实体追踪 + 指代消解</text>
"""

    # Turn 1
    s += f"""
<rect x="{RX+20}" y="180" width="500" height="50" rx="8" fill="{BG}" stroke="{BORDER}"/>
<text x="{RX+34}" y="202" font-size="11" fill="{DIM}">第 1 轮</text>
<text x="{RX+34}" y="220" font-size="13" fill="{TEXT}">茅台和五粮液2023年毛利率哪家高？</text>
<rect x="{RX+420}" y="190" width="86" height="30" rx="15" fill="{ACCENT}" opacity="0.15"/>
<text x="{RX+463}" y="210" text-anchor="middle" font-size="11" fill="{ACCENT}">存入记忆</text>
"""

    # Turn 2
    s += f"""
<rect x="{RX+20}" y="248" width="500" height="50" rx="8" fill="{BG}" stroke="{BORDER}"/>
<text x="{RX+34}" y="270" font-size="11" fill="{DIM}">第 2 轮</text>
<text x="{RX+34}" y="288" font-size="13" fill="{TEXT}">那另一家呢？</text>
"""

    # 改写横幅
    s += f"""
<rect x="{RX+20}" y="316" width="500" height="56" rx="8" fill="{ACCENT}" opacity="0.12" stroke="{ACCENT}" stroke-width="1.5"/>
<text x="{RX+34}" y="338" font-size="11" font-weight="700" fill="{ACCENT}">🧠  短期记忆改写</text>
<text x="{RX+34}" y="358" font-size="12" fill="{TEXT}">"那另一家呢？"  →  <tspan font-weight="700" fill="{ACCENT}">"五粮液呢？"</tspan></text>
"""

    # 正确响应
    s += f"""
<rect x="{RX+20}" y="388" width="500" height="98" rx="8" fill="{BG}" stroke="{GREEN}" stroke-width="1.5"/>
<text x="{RX+34}" y="410" font-size="11" font-weight="700" fill="{GREEN}">✓  Agent 响应</text>
<text x="{RX+34}" y="432" font-size="12" fill="{TEXT}">五粮液 2023 年毛利率为 75.79%，</text>
<text x="{RX+34}" y="450" font-size="12" fill="{TEXT}">比茅台低 16.17 个百分点。</text>
<text x="{RX+34}" y="476" font-size="11" fill="{GREEN}">结果：一次到位 / 体验流畅</text>
"""

    # 底部脚注
    s += f"""
<text x="{W/2}" y="540" text-anchor="middle" font-size="12" fill="{DIM}">仅在 Python 端做指代消解（不改 LLM），可解释、可调试、节省 token</text>
</svg>
"""

    (OUT / "demo-comparison.svg").write_text(s, encoding="utf-8")
    print("✓ demo-comparison.svg")


# ══════════════════════════════════════════════════════════════════════════════
# 2. architecture.svg
# ══════════════════════════════════════════════════════════════════════════════

def make_architecture():
    W, H = 1100, 620
    s = svg_header(W, H, "架构图")
    s += f'<text x="{W/2}" y="42" text-anchor="middle" font-size="22" font-weight="700" fill="{TEXT}">架构与数据流</text>\n'

    # ── 顶层：用户 ──
    s += f"""
<rect x="450" y="80" width="200" height="50" rx="25" fill="{PANEL}" stroke="{TEXT}" stroke-width="1.5"/>
<text x="550" y="110" text-anchor="middle" font-size="14" font-weight="700" fill="{TEXT}">👤  User Question</text>
"""

    # 箭头向下
    s += f'<line x1="550" y1="130" x2="550" y2="160" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<polygon points="550,160 545,150 555,150" fill="{TEXT}"/>\n'

    # ── 中层左：记忆模块 ──
    s += f"""
<rect x="80" y="170" width="320" height="160" rx="12" fill="{PANEL}" stroke="{ACCENT}" stroke-width="2"/>
<text x="240" y="200" text-anchor="middle" font-size="15" font-weight="700" fill="{ACCENT}">💾  Short-Term Memory</text>
<text x="100" y="230" font-size="12" fill="{DIM}">•  JSON 持久化（每个 session 一文件）</text>
<text x="100" y="252" font-size="12" fill="{DIM}">•  Entity Tracker：公司 + 指标 + 年份</text>
<text x="100" y="274" font-size="12" fill="{DIM}">•  Anaphora Resolver：</text>
<text x="124" y="294" font-size="11" fill="{ACCENT}">  contrast（那另一家）/ repeat（再来一次）</text>
<text x="100" y="316" font-size="12" fill="{DIM}">•  Metric Focus：沿用上一轮核心指标</text>
"""

    # 中层右：ReAct 循环
    s += f"""
<rect x="430" y="170" width="590" height="280" rx="12" fill="{PANEL}" stroke="{BLUE}" stroke-width="2"/>
<text x="725" y="200" text-anchor="middle" font-size="15" font-weight="700" fill="{BLUE}">🔁  ReAct Loop（≤ 10 步）</text>
"""
    # 三个 box：Thought / Action / Observation
    box_y = 230
    box_w = 170
    for i, (label, color, x) in enumerate([
        ("Thought\nLLM Reasoning", BLUE, 450),
        ("Action\nTool Call",     YELLOW, 640),
        ("Observation\nTool Result", GREEN, 830),
    ]):
        s += f'<rect x="{x}" y="{box_y}" width="{box_w}" height="80" rx="8" fill="{BG}" stroke="{color}" stroke-width="1.5"/>\n'
        for j, line in enumerate(label.split("\n")):
            color_main = color if j == 0 else DIM
            weight = "700" if j == 0 else "400"
            s += f'<text x="{x+box_w/2}" y="{box_y+30+j*22}" text-anchor="middle" font-size="13" font-weight="{weight}" fill="{color_main}">{line}</text>\n'

    # 循环箭头
    s += f'<path d="M {450+box_w} {box_y+40} L {640-10} {box_y+40}" stroke="{TEXT}" stroke-width="1.2" fill="none"/>\n'
    s += f'<polygon points="{640-10},{box_y+40} {630,{box_y+35}} {630,{box_y+45}}" fill="{TEXT}"/>\n'
    s += f'<path d="M {640+box_w} {box_y+40} L {830-10} {box_y+40}" stroke="{TEXT}" stroke-width="1.2" fill="none"/>\n'
    s += f'<polygon points="{830-10},{box_y+40} {820,{box_y+35}} {820,{box_y+45}}" fill="{TEXT}"/>\n'

    # 反向箭头（回到 Thought）
    s += f'<path d="M {830+box_w/2} {box_y+80} Q {640} {box_y+130}, {450+box_w/2} {box_y+80}" stroke="{TEXT}" stroke-width="1.2" stroke-dasharray="4,3" fill="none"/>\n'
    s += f'<polygon points="{450+box_w/2},{box_y+80} {458,{box_y+88}} {458,{box_y+72}}" fill="{TEXT}"/>\n'
    s += f'<text x="725" y="{box_y+128}" text-anchor="middle" font-size="11" fill="{DIM}">循环直到 Final Answer 或 max_steps</text>\n'

    # Final Answer
    s += f'<rect x="540" y="370" width="370" height="55" rx="10" fill="{ACCENT}" opacity="0.18" stroke="{ACCENT}" stroke-width="1.5"/>\n'
    s += f'<text x="725" y="402" text-anchor="middle" font-size="14" font-weight="700" fill="{ACCENT}">✅  Final Answer</text>\n'

    # ── 底层：5 个工具 ──
    s += f"""
<rect x="80" y="490" width="940" height="100" rx="12" fill="{PANEL}" stroke="{BORDER}" stroke-width="1.5"/>
<text x="550" y="518" text-anchor="middle" font-size="14" font-weight="700" fill="{TEXT}">🔧  5 Tools</text>
"""
    tools = [
        ("company_lookup",    "公司→代码"),
        ("rag_search",        "FAISS 语义"),
        ("financial_indicator", "AkShare 财务"),
        ("stock_price",        "AkShare 行情"),
        ("calculator",         "数学计算"),
    ]
    tw = 165
    sx = 100
    for i, (name, desc) in enumerate(tools):
        x = sx + i * (tw + 15)
        s += f'<rect x="{x}" y="535" width="{tw}" height="45" rx="6" fill="{BG}" stroke="{BORDER}"/>\n'
        s += f'<text x="{x+tw/2}" y="555" text-anchor="middle" font-size="11" font-weight="700" fill="{YELLOW}">{name}</text>\n'
        s += f'<text x="{x+tw/2}" y="572" text-anchor="middle" font-size="10" fill="{DIM}">{desc}</text>\n'

    s += "</svg>\n"
    (OUT / "architecture.svg").write_text(s, encoding="utf-8")
    print("✓ architecture.svg")


# ══════════════════════════════════════════════════════════════════════════════
# 3. rewrite-flow.svg —— 指代消解流程
# ══════════════════════════════════════════════════════════════════════════════

def make_rewrite_flow():
    W, H = 900, 540
    s = svg_header(W, H, "指代消解流程")
    s += f'<text x="{W/2}" y="40" text-anchor="middle" font-size="22" font-weight="700" fill="{TEXT}">指代消解流程</text>\n'

    # 起点
    s += f"""
<rect x="340" y="80" width="220" height="50" rx="25" fill="{PANEL}" stroke="{TEXT}" stroke-width="1.5"/>
<text x="450" y="110" text-anchor="middle" font-size="13" font-weight="700" fill="{TEXT}">用户追问</text>
"""

    # 菱形判定
    s += f"""
<polygon points="450,160 620,210 450,260 280,210" stroke="{BLUE}" stroke-width="1.5" fill="{PANEL}"/>
<text x="450" y="205" text-anchor="middle" font-size="12" font-weight="700" fill="{BLUE}">包含指代触发词？</text>
<text x="450" y="222" text-anchor="middle" font-size="10" fill="{DIM}">那另一家 / 再来一次 / 那呢</text>
"""

    # 连接线
    s += f'<line x1="450" y1="130" x2="450" y2="160" stroke="{TEXT}" stroke-width="1.5"/>\n'

    # 两条分支
    # 左：否 → 原样
    s += f'<text x="180" y="200" text-anchor="middle" font-size="11" fill="{DIM}">否</text>\n'
    s += f'<line x1="280" y1="210" x2="180" y2="210" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<rect x="60" y="185" width="120" height="50" rx="8" fill="{PANEL}" stroke="{BORDER}"/>\n'
    s += f'<text x="120" y="215" text-anchor="middle" font-size="13" fill="{TEXT}">原样发送</text>\n'

    # 右：是
    s += f'<text x="720" y="200" text-anchor="middle" font-size="11" fill="{DIM}">是</text>\n'
    s += f'<line x1="620" y1="210" x2="780" y2="210" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<polygon points="780,210 770,205 770,215" fill="{TEXT}"/>\n'

    # 第二个判定
    s += f'<polygon points="800,210 880,260 800,310 720,260" stroke="{BLUE}" stroke-width="1.5" fill="{PANEL}"/>\n'
    s += f'<text x="800" y="255" text-anchor="middle" font-size="11" font-weight="700" fill="{BLUE}">哪类？</text>\n'

    # contrast 分支
    s += f'<text x="755" y="290" text-anchor="middle" font-size="10" fill="{DIM}">对比</text>\n'
    s += f'<line x1="720" y1="260" x2="660" y2="260" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<rect x="430" y="320" width="230" height="70" rx="8" fill="{PANEL}" stroke="{ACCENT}" stroke-width="1.5"/>\n'
    s += f'<text x="545" y="345" text-anchor="middle" font-size="13" font-weight="700" fill="{ACCENT}">contrast 策略</text>\n'
    s += f'<text x="545" y="365" text-anchor="middle" font-size="10" fill="{DIM}">从上一轮实体里挑未提及的</text>\n'
    s += f'<text x="545" y="380" text-anchor="middle" font-size="10" fill="{DIM}">替换"那另一家"为具体公司名</text>\n'

    # repeat 分支
    s += f'<text x="845" y="290" text-anchor="middle" font-size="10" fill="{DIM}">重复</text>\n'
    s += f'<line x1="800" y1="310" x2="800" y2="340" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<rect x="685" y="345" width="230" height="70" rx="8" fill="{PANEL}" stroke="{ACCENT}" stroke-width="1.5"/>\n'
    s += f'<text x="800" y="370" text-anchor="middle" font-size="13" font-weight="700" fill="{ACCENT}">repeat 策略</text>\n'
    s += f'<text x="800" y="390" text-anchor="middle" font-size="10" fill="{DIM}">沿用上一轮 metric_focus</text>\n'

    # 底部：改写后的问题
    s += f'<line x1="545" y1="395" x2="545" y2="440" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<line x1="800" y1="420" x2="800" y2="440" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<line x1="545" y1="440" x2="800" y2="440" stroke="{TEXT}" stroke-width="1.5"/>\n'
    s += f'<line x1="450" y1="440" x2="450" y2="470" stroke="{TEXT}" stroke-width="1.5"/>\n'

    s += f'<rect x="240" y="470" width="430" height="50" rx="25" fill="{ACCENT}" opacity="0.2" stroke="{ACCENT}" stroke-width="2"/>\n'
    s += f'<text x="455" y="500" text-anchor="middle" font-size="13" font-weight="700" fill="{ACCENT}">改写后的问题 → ReAct Loop</text>\n'

    s += "</svg>\n"
    (OUT / "rewrite-flow.svg").write_text(s, encoding="utf-8")
    print("✓ rewrite-flow.svg")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_comparison()
    make_architecture()
    make_rewrite_flow()
    print(f"\n所有 SVG 已写入 {OUT}/")