# ReAct LLM Memory Agent

**ReAct Financial Agent with persistent short-term memory, entity tracking, and anaphora resolution**

> 让 Agent 能理解「那另一家呢？」这类追问。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org)

---

## 🎯 问题

多轮 Agent 对话里的经典失败：

```
用户：宁德时代和比亚迪的营收对比怎么样？
Agent：...（回答了对比）

用户：那它的新能源业务占比呢？        ← "它" 指谁？
Agent：❌ 丢失上下文，只能反问
```

根本原因：**上下文窗口 ≠ 记忆**。把历史全部塞进 prompt，会遇到：

- **成本线性增长** —— 每轮都要重传全部历史
- **注意力稀释** —— 长上下文里早期信息权重下降
- **指代消解失败** —— "它/他们/另一家"无法解析到具体实体

---

## ✨ 方案：外置记忆 + 实体追踪

```
用户输入
   │
   ▼
┌──────────────────┐
│  指代消解          │  "它" → 上一轮实体集合中的哪个？
│  Anaphora         │  规则优先 + LLM 兜底
└────────┬─────────┘
         ▼
┌──────────────────┐
│  实体追踪          │  Entity Tracking
│  Track            │  → 维护对话中的实体注册表
│                   │     {宁德时代: ..., 比亚迪: ...}
└────────┬─────────┘
         ▼
┌──────────────────┐
│  短期记忆检索      │  只取相关片段，不传全量历史
│  Retrieve        │  → 按实体 + 语义双重召回
└────────┬─────────┘
         ▼
┌──────────────────┐
│  ReAct 循环        │  Thought → Action → Observation
└──────────────────┘
```

### 核心设计

**① 实体注册表（Entity Registry）**

对话过程中维护一个结构化实体表，而不是靠自然语言回忆：

```python
entities = EntityRegistry([
    Entity(id="E1", name="宁德时代", type="company", first_mention_turn=1),
    Entity(id="E2", name="比亚迪",   type="company", first_mention_turn=1),
])
```

**② 指代消解的三级策略**

| 优先级 | 规则 | 例子 |
|---|---|---|
| 1 | 最近提及原则 | 「它」→ 上一轮最后提到的实体 |
| 2 | 语义匹配 | 「新能源那家」→ 类型/属性匹配到 E1 |
| 3 | LLM 兜底 | 以上都不确定时才调模型，附候选集 |

**成本远低于每轮把历史全塞进 prompt。**

**③ 记忆检索：实体 + 语义双通道**

```
最终上下文 = 实体相关片段（精确） + 语义相关片段（模糊补充）
```

---

## 🔬 合并说明

本仓库合并了原 `contextual-retrieval-for-user-memory`（上下文检索实验），
两者属于同一问题域 —— **如何让 Agent 记住并正确使用上下文**。

```
原 react-llm-memory-agent   ──┐
                               ├──▶ react-llm-memory-agent（统一）
原 contextual-retrieval-for-user-memory ──┘
```

---

## 🚀 快速开始

```bash
git clone https://github.com/KBber/react-llm-memory-agent.git
cd react-llm-memory-agent
pip install -e .
```

```python
from memory_agent import MemoryAgent

agent = MemoryAgent()

agent.run("宁德时代和比亚迪的营收对比怎么样？")
agent.run("那它的新能源业务占比呢？")
#        ↑ 指代消解 → 宁德时代 → 只检索相关记忆片段
```

---

## 💡 设计取舍

| 决策 | 选择 | 理由 |
|---|---|---|
| 记忆存储 | 外置结构化，而非全量塞 prompt | 成本线性增长 vs 结构化召回 |
| 指代消解 | 规则优先，LLM 兜底 | 规则零延迟零成本，LLM 只处理难例 |
| 记忆粒度 | 实体绑定片段 | 比摘要更精确，比全文更省 |
| 遗忘策略 | 滑动窗口 + 实体热度 | 长期对话不爆上下文 |

---

## 📈 路线图

- [x] 实体注册表与追踪
- [x] 三级指代消解（规则 → 语义 → LLM）
- [x] 实体 + 语义双通道记忆检索
- [x] 上下文检索实验（原 contextual-retrieval 仓库合并）
- [ ] 多轮一致性评测集
- [ ] 记忆衰减与冲突消解
- [ ] 跨会话长期记忆

---

## 📄 License

MIT
