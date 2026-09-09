# 实验报告：ReAct Financial Agent 多轮记忆扩展

> 项目路径：`课件/week12 agent/react_financial_agent/`
> 运行日期：2026-09-09
> 实验者：Claude (MiniMax-M3) 协助实现并验证

---

## 一、项目概述

原项目是一个基于 ReAct 范式的 A 股金融分析 Agent，支持以下 5 个工具：

| 工具 | 用途 |
|------|------|
| `company_lookup` | 公司名 → 股票代码 |
| `rag_search` | FAISS 语义检索年报（10353 条 1024 维向量） |
| `calculator` | 安全数学表达式计算 |
| `financial_indicator` | AkShare 实时财务指标 |
| `stock_price` | AkShare 历史股价与涨跌幅 |

本次扩展在原项目基础上新增：

1. **持久化短期记忆** —— 每个会话独立 JSON 文件，跨进程持久化
2. **实体追踪** —— 自动识别问题中提到的公司 + 指标 + 年份
3. **指代消解** —— 处理"那另一家呢""再来一次"等附加提问

---

## 二、新增/修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `src/memory.py` | **新增** (285 行) | 短期记忆 + 实体追踪 + 指代消解 |
| `src/react_manual.py` | 修改 | 接入 `session_id`/`memory` 参数；改写结果通过 SSE 推送 |
| `src/react_function_calling.py` | 修改 | 同上 |
| `src/agent.py` | 修改 | CLI 增加 `--session` 与 `--reset` |
| `src/serve.py` | 重写 | REST API 改为 `/sessions/{sid}/query/{mode}` 模式 + 会话 CRUD |
| `index.html` | 重写 | 新增记忆侧栏、追问示例、改写横幅展示 |
| `tests/test_memory.py` | **新增** | memory 模块 36 个单元测试 |
| `tests/test_e2e.py` | **新增** | REST API + ReAct + 记忆闭环端到端测试 |
| `MEMORY_GUIDE.md` | **新增** | 完整使用文档 |
| `REPORT.md` | **新增** | 本文档 |

新增依赖：无（只使用标准库 + 已有的 openai/fastapi/faiss/uvicorn）。

---

## 三、核心设计：短期记忆结构

每个 session 一个 JSON 文件，路径 `data/memory/<session_id>.json`：

```json
{
  "session_id": "sess_abc12345",
  "updated_at": 1757420000.0,
  "turns": [
    {
      "turn_id": 1,
      "user_question": "贵州茅台和五粮液2023年毛利率差多少？",
      "rewritten_question": null,
      "was_rewritten": false,
      "rewrite_reason": null,
      "answer": "茅台高出16.17个百分点",
      "entities": [
        {"name": "贵州茅台", "code": "600519", "metric": "毛利率", "year": "2023年"},
        {"name": "五粮液",   "code": "000858", "metric": "毛利率", "year": "2023年"}
      ],
      "metric_focus": "毛利率",
      "tools_used": ["company_lookup", "financial_indicator", "calculator"],
      "timestamp": 1757420000.0
    },
    {
      "turn_id": 2,
      "user_question": "那另一家呢？",
      "rewritten_question": "五粮液呢？",
      "was_rewritten": true,
      "rewrite_reason": "对比类指代 → 替换为 五粮液",
      "answer": "五粮液2023年毛利率为75.79%",
      "entities": [{"name": "五粮液", "code": "000858"}],
      "metric_focus": null,
      "tools_used": ["company_lookup", "financial_indicator"]
    }
  ]
}
```

---

## 四、指代消解规则与示例

`src/memory.py` 中的 `rewrite_follow_up()` 是核心逻辑，分三类策略：

| 触发词类别 | 关键词 | 策略 | 改写逻辑 |
|-----------|--------|------|---------|
| 对比类 | 那另一家、那另一个、另外一家、那家 | `contrast` | 从上一轮实体里挑"未在本轮被提到"的最后一个，替换进去 |
| 重复类 | 那呢、再来一次、也一样 | `repeat` | 沿用上一轮 `metric_focus`，在 question 后追加提示 |
| 时间延续类 | 近一年、去年、前年 | `repeat` | 同上（沿用上一轮实体） |
| 无触发词 | — | — | 不改写，原样发送 |

**改写示例**（上下文：上一轮提到 [贵州茅台, 五粮液]，指标=毛利率）：

| 用户输入 | 改写结果 | 策略 |
|---------|---------|------|
| `那另一家呢？` | `五粮液呢？` | contrast |
| `那茅台呢？` | （不改写） | — |
| `再来一次` | `再来一次（沿用上一轮关注的指标：毛利率）` | repeat |
| `宁德时代呢？` | （不改写） | — |

设计取舍：
- 改写在 **Python 端做**，不依赖 LLM —— 可控、可解释、节省 token
- 同时在 system prompt 注入「[上一轮对话记忆]」段，让 LLM 也能感知上下文（即便改写失败兜底也能理解）

---

## 五、运行验证

### 5.1 单元测试：`tests/test_memory.py`

```
memory.py 单元测试：36/36 通过
```

覆盖范围：
- 实体抽取（公司名识别、别名映射、未登录公司、metric/year 携带）
- 年份抽取（YYYY年、YYYY-YYYY、YYYY到YYYY、裸 YYYY、无年份）
- 指标焦点识别
- 指代消解 contrast / repeat / 不触发 / 无上一轮 4 大分支
- 实体收集（从工具步进结果反查代码）
- 持久化往返（写入 → 重新加载 → 内容一致）

### 5.2 端到端测试：`tests/test_e2e.py`

启动 in-process uvicorn（端口 8765），用 mock 工具 + mock LLM 走完整流程：

```
[1] 创建会话 sess_e2e_1788959004
[2] 首轮提问 '贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？'
  收到事件: ['start', 'action', 'action', 'action', 'action', 'action', 'final', 'memory_snapshot', 'done']
  action=True final=True snapshot=True
[3] 追问 '那另一家呢？'
  收到事件: ['start', 'memory_rewrite', 'final', 'memory_snapshot', 'done']
  改写横幅: [{'type': 'memory_rewrite', 'raw_question': '那另一家呢？', 'question': '五粮液呢？', 'strategy': 'contrast', 'reason': '对比类指代 → 替换为 五粮液'}]
[4] 检查会话记忆
  Turn 1 [原样]: 贵州茅台和五粮液2023年的毛利率哪家更高？差多少个百分点？
    实体: [贵州茅台、五粮液]
    指标: 毛利率
    工具: ['company_lookup', 'company_lookup', 'financial_indicator', 'financial_indicator', 'calculator']
  Turn 2 [✓被改写]: 那另一家呢？
    改写后: 五粮液呢？
    实体: [五粮液]
[5] 列出所有会话 → 共 1 个
[6] 清空会话 → turns 数: 0
[7] Function Calling 版端到端 → action×5 + final，实体=[贵州茅台, 五粮液]
```

测试通过的关键点：
- ✅ ReAct 循环在 final 分支正常终止（修复了 for-else 重构后未生效的边界）
- ✅ 改写横幅以独立 SSE 事件推送，前端可识别
- ✅ 记忆自动写入 JSON 文件，跨"轮次"可读
- ✅ DELETE 清空会话生效
- ✅ FC 版与 manual 版行为对齐

### 5.3 模块自检：`memory.py __main__`

```
[Turn 1] 贵州茅台和五粮液2023年的毛利率哪家更高？
  实体: ['贵州茅台', '五粮液']
  指标: 毛利率
[Turn 2 raw]    那另一家呢？
[Turn 2 rewritten] 五粮液呢？
  改写: True  策略: contrast  理由: 对比类指代 → 替换为 五粮液
```

---

## 六、运行环境

| 项 | 值 |
|----|---|
| Python | 3.14.6 (Windows 10) |
| openai | 1.109.1 |
| fastapi | 已安装 |
| faiss-cpu | 已安装（FAISS 索引 10353 条 × 1024 维 可加载） |
| akshare | **未安装** —— AkShare 工具在本轮实验中未触发，运行时会被 `try/except` 兜底返回错误字符串 |
| DASHSCOPE_API_KEY | 已设置（来自桌面 key.txt） |
| AGENT_MODEL | qwen-max（manual 版）/ deepseek-v4-flash（FC 版，注释中） |

> **本轮实验以 mock 形式完成 ReAct 闭环验证**，未对真实 LLM 发起调用。原因是单元测试与端到端测试已能完整覆盖记忆模块 + REST API + ReAct 流程；真实 LLM 调用对验证"指代消解是否正确改写"无增量信息，反而消耗 token 与时长。

---

## 七、待补足的真实运行

下一步若需真实 LLM 验证：

```bash
cd react_financial_agent
export DASHSCOPE_API_KEY="sk-..."
pip install akshare
# 单元测试
python tests/test_memory.py
# 端到端（无 mock）
uvicorn src.serve:app --host 0.0.0.0 --port 8000
# CLI 多轮
python src/agent.py --mode manual --session demo \
    --question "贵州茅台和五粮液2023年毛利率哪家高？"
python src/agent.py --mode manual --session demo \
    --question "那另一家呢？"
```

预期（基于本项目原有 ARCHITECTURE.md 中的示例耗时）：
- 首轮：5 步工具调用 + 1 final，约 60–70 秒
- 追问（改写后）：3 步工具调用 + 1 final，约 35–40 秒
- 改写横幅在前端顶部紫色显示，"当前会话记忆"侧栏实时刷新

---

## 八、局限与扩展方向

| 当前实现 | 局限 | 建议扩展 |
|---------|------|---------|
| 公司词典硬编码 5 家 | 新增公司需同步改 `tools.py` 与 `memory.py` | 用 NER 模型处理未登录公司 |
| 改写策略 = 规则匹配 | 复杂语义（"前两家中表现更稳的那家"）依赖 LLM 兜底 | 增加 embedding 检索"最相关历史 turn" |
| 记忆按 session 隔离 | 跨 session 不共享 | 加全局 long-term memory（向量库） |
| 改写触发词固定 | 新问法漏网 | 从用户日志里挖掘高频表达，自动补充 |
| `metric_focus` 仅取第一个匹配 | "茅台的毛利率和ROE"会丢掉 ROE | 改用列表，循环追问支持多指标切换 |

---

## 九、关键文件路径速查

```
react_financial_agent/
├── REPORT.md                          ← 本文档
├── MEMORY_GUIDE.md                    ← 使用指南
├── ARCHITECTURE.md                    ← 原项目架构
├── index.html                         ← Web UI（已改造）
├── src/
│   ├── memory.py                      ← 短期记忆核心
│   ├── react_manual.py                ← 手写版 ReAct（已接入记忆）
│   ├── react_function_calling.py      ← FC 版 ReAct（已接入记忆）
│   ├── agent.py                       ← CLI 入口
│   ├── serve.py                       ← FastAPI 服务
│   ├── tools.py                       ← 5 个工具
│   └── evaluate.py                    ← 两种实现对比
├── tests/
│   ├── test_memory.py                 ← 36 个单元测试
│   └── test_e2e.py                    ← 端到端集成测试
└── data/
    └── memory/                        ← 运行时自动创建的 JSON 持久化目录
```