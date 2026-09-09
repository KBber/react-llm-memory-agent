# MEMORY_GUIDE.md — 短期记忆与指代消解使用指南

本项目在原 ReAct Financial Agent 基础上新增了 **多轮对话短期记忆** 与 **指代消解**能力，
使 Agent 能理解"那另一家呢""那个呢""再看看这个"这类附加提问。

---

## 1. 快速体验（Web UI）

```bash
cd react_financial_agent
pip install -r requirements.txt
export DASHSCOPE_API_KEY="sk-xxx"
uvicorn src.serve:app --host 0.0.0.0 --port 8000
```

浏览器打开 `http://localhost:8000`。

**演示脚本（侧栏会实时刷新记忆）：**

1. 切到「手写 Prompt 解析」模式
2. 第一轮输入：  
   `茅台和五粮液2023年毛利率差多少？`
3. 第二轮输入：  
   `那另一家呢？`

你会看到：
- 步骤卡片顶部出现一条紫色横幅："🧠 短期记忆改写：那另一家呢？ → 五粮液呢？"
- Agent 不再查茅台，只查五粮液
- 右侧"当前会话记忆"列出两轮：第二轮显示被改写后的真实问题
- 第二轮出现的实体只有「五粮液」一个

继续追问（验证实体追踪依然生效）：
- `宁德时代呢？` → 不会被改写（已经提到了具体公司名），Agent 直接查宁德
- `它的净利润呢？` → 沿用上一轮指标，但未指定公司，模型从历史里推
- `再来一次` → 命中「重复类」触发，沿用指标提示

---

## 2. CLI 用法

```bash
# 第一轮（建立记忆）
python src/agent.py --mode manual --session demo \
    --question "茅台和五粮液2023年毛利率哪家高？"

# 第二轮（自动改写指代）
python src/agent.py --mode manual --session demo \
    --question "那另一家呢？"

# 清空会话记忆重新演示
python src/agent.py --mode manual --session demo --reset
```

`--session` 参数指定会话 ID，记忆自动写入 `data/memory/<session_id>.json`。

---

## 3. 短期记忆数据结构

每个会话一个 JSON 文件，路径 `react_financial_agent/data/memory/<session_id>.json`：

```json
{
  "session_id": "sess_abc12345",
  "updated_at": 1757420000.0,
  "turns": [
    {
      "turn_id": 1,
      "user_question": "茅台和五粮液2023年毛利率差多少？",
      "rewritten_question": null,
      "was_rewritten": false,
      "rewrite_reason": null,
      "answer": "茅台高出16.17个百分点",
      "entities": [
        {"name": "贵州茅台", "code": "600519", "metric": "毛利率", "year": "2023"},
        {"name": "五粮液",   "code": "000858", "metric": "毛利率", "year": "2023"}
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
      "answer": "...",
      "entities": [{"name": "五粮液", "code": "000858"}],
      "metric_focus": null,
      "tools_used": ["company_lookup", "financial_indicator"]
    }
  ]
}
```

字段说明：
- `entities` —— 一轮对话中 Agent 实际查询过的公司 + 指标 + 年份
- `metric_focus` —— 提问的核心指标，下一轮指代消解时沿用
- `was_rewritten` / `rewritten_question` —— 是否被改写、改写后真正发给 Agent 的问题

---

## 4. 指代消解规则

`src/memory.py` 中的 `rewrite_follow_up()` 是核心逻辑：

| 触发词 | 策略 | 改写逻辑 |
|--------|------|---------|
| 那另一家、那另一个、另外一家、那家 | **对比类** `contrast` | 从上一轮所有实体里选"未在本轮被提到"的最后一个，替换进去 |
| 那呢、再来一次、也一样 | **重复类** `repeat` | 沿用上一轮 `metric_focus`，在 question 后追加提示 |
| 无触发词 | 不改写 | 原样发送 |

替换示例（上下文：上一轮提到 [茅台, 五粮液]）：

| 用户输入 | 改写结果 | 说明 |
|---------|---------|------|
| `那另一家呢？` | `五粮液呢？` | 取未提及的最后一个 |
| `那茅台呢？` | （不触发） | 已具体提到 |
| `那茅台和宁德时代呢？` | （不触发） | 未提及的"宁德时代"已被用户自己写出，触发器仅指代场景才生效 |
| `再来一次` | `再来一次（沿用上一轮关注的指标：毛利率）` | 提示 LLM 沿用 |

改写后的问题会被送入 ReAct 循环；同时在 system prompt 末尾追加「[上一轮对话记忆]」段，
让 LLM 也能感知上下文（即便改写失败兜底也能理解）。

---

## 5. 程序化使用

```python
from memory import ShortTermMemory, rewrite_follow_up

mem = ShortTermMemory("my_chat")
rw = rewrite_follow_up("那另一家呢？", mem)
if rw["rewritten"]:
    print("改写:", rw["question"], "| 策略:", rw["strategy"])

# 一轮结束后写记忆
from memory import extract_entities, collect_entities_from_steps, detect_metric_focus
mem.add_turn(
    user_question="那另一家呢？",
    answer="...",
    entities=collect_entities_from_steps(steps),
    metric_focus=detect_metric_focus("那另一家呢？"),
    tools_used=["company_lookup", "financial_indicator"],
)
```

---

## 6. Web API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/sessions` | 创建新会话，返回 `{session_id}` |
| `GET`  | `/sessions` | 列出所有历史会话 |
| `GET`  | `/sessions/{sid}` | 查看会话完整记忆 |
| `DELETE` | `/sessions/{sid}` | 清空会话记忆 |
| `POST` | `/sessions/{sid}/query/manual` | 手写版 ReAct（SSE 流式） |
| `POST` | `/sessions/{sid}/query/fc` | Function Calling 版（SSE 流式） |

---

## 7. 局限与扩展方向

当前实现的取舍：

| 决策 | 取舍 | 影响 |
|------|------|------|
| 短期记忆 = 单会话 JSON | 简单 | 进程重启后记忆仍在，但跨会话不共享 |
| 实体词典硬编码 5 家公司 | 与工具一致 | 新增公司需同时改 `tools.py` 与 `memory.py` |
| 指代消解 = 规则匹配 | 可控可解释 | 复杂语义（如"前两家中表现更稳的那家"）仍依赖 LLM 兜底 |
| 改写策略优先于 LLM | 节省 token | 边界 case 可能改写错，需结合 system prompt 中的历史段作为兜底 |

后续可扩展：
- 把 `extract_entities` 升级为 NER 模型处理未登录公司
- 引入 embedding 检索"最相关的历史 turn"作为长期记忆
- 指代消解增加更多触发词和歧义消解（如"那个做新能源的呢"）
- 把 `metric_focus` 与 `year` 纳入时间线追踪，支持"近三年趋势"型复合追问