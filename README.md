# 智能体记忆系统初步框架

## 1. 文档目标

本文档用于描述一个面向智能体的初步记忆系统框架，并说明它未来如何从轻量 MVP 演进为可治理、可验证、可扩展的长期经验系统。

这里的“记忆”不是简单地保存聊天记录，也不是把所有内容塞进向量库。一个可靠的智能体记忆系统应该回答四个问题：

- 什么值得记
- 记住以后如何证明它可信
- 什么时候应该检索出来
- 什么时候应该修正、合并或遗忘

本文档的核心判断是：

> 记忆系统不是存储系统，而是经验治理系统。

## 2. 当前实现路线

第一版推荐采用 Python 实现。

```text
Python
+ FastAPI
+ Pydantic
+ SQLite
+ SQLite FTS5
+ pytest
```

选择 Python 的原因：

- 适合快速实现记忆核心逻辑
- Pydantic 很适合定义候选记忆、写入决策、检索结果等结构
- SQLite 和 FTS5 可以覆盖 MVP 阶段的大部分存储与检索需求
- 后续接向量库、图谱库、模型抽取、定时任务都比较自然
- 更适合先做研究型和原型型系统，再逐步产品化

TypeScript 仍然可以作为后续方向，用于：

- Web 管理界面
- SDK
- MCP Server
- Agent 前端工作台
- 与 Node 生态的工具集成

但记忆系统的第一版核心不建议同时维护两套语言实现。

## 3. 当前代码状态

已实现 Phase 1 的最小 Event Log MVP：

```text
src/memory_system/
  schemas.py      Pydantic 事件结构
  event_log.py    SQLite 事件日志、查询和基础敏感信息处理
tests/
  test_event_log.py
```

运行测试：

```bash
python -m pytest
```

最小使用示例：

```python
from memory_system import EventCreate, EventLog

log = EventLog("data/memory.sqlite")
event = log.record_event(
    EventCreate(
        event_type="user_message",
        content="以后技术文档默认用中文。",
        source="conversation",
        scope="global",
        task_id="task-1",
    )
)

loaded = log.get_event(event.id)
```

## 4. 设计原则

### 4.1 少记优先

错误、重复、过期和未经验证的记忆会污染智能体行为。系统默认应该保守，优先避免错误写入，而不是追求“什么都记住”。

### 4.2 分层管理

不同类型的记忆应该有不同生命周期、检索方式和写入门槛。用户长期偏好、项目事实、工具规则、排错经验和临时上下文不应该混在同一个池子里。

### 4.3 证据优先

每条长期记忆都应该尽量带有来源、时间、置信度和适用范围。智能体在使用记忆时，应该能够区分：

- 用户明确说过
- 工具结果验证过
- 从历史对话中总结得出
- 可能已经过期

### 4.4 可修订而非覆盖

记忆不是一次写入后永远正确。系统需要支持冲突检测、版本记录、降权、归档和废弃。

### 4.5 检索服务于任务

记忆检索不应该只是简单的 `topK similarity search`。系统应该先判断当前任务需要哪类记忆，再选择合适的检索策略。

## 5. 文档目录

- [01-framework-overview.md](docs/01-framework-overview.md)：整体概念、记忆分层和生命周期
- [02-architecture.md](docs/02-architecture.md)：系统模块和端到端流程
- [03-data-model.md](docs/03-data-model.md)：核心数据结构、表设计和字段说明
- [04-write-governance.md](docs/04-write-governance.md)：写入门禁、冲突检测、敏感信息和排错经验模板
- [05-retrieval-and-context.md](docs/05-retrieval-and-context.md)：混合检索、上下文组装和记忆注入策略
- [06-evolution-roadmap.md](docs/06-evolution-roadmap.md)：从 Python MVP 到高级记忆系统的演进路线
- [07-implementation-checklist.md](docs/07-implementation-checklist.md)：Python 实施清单、模块结构、接口和测试用例
- [08-mainstream-frameworks.md](docs/08-mainstream-frameworks.md)：主流记忆框架对比和可借鉴设计
- [09-verification-and-testing.md](docs/09-verification-and-testing.md)：验证指标、测试分层、黄金测试集和上线验收

## 6. 初始推荐路线

推荐从一个保守但结构清晰的 MVP 开始：

```text
Event Log
  -> Memory Candidate Extractor
  -> Write Policy Gate
  -> Structured Memory Store
  -> Retrieval Planner
  -> Context Composer
```

第一阶段不要急于全自动写入，也不要过早引入复杂向量架构。更稳妥的顺序是：

1. 先记录事件日志。
2. 从事件中抽取候选记忆。
3. 对候选记忆做人工确认或严格规则判断。
4. 将确认后的记忆写入结构化存储。
5. 用全文检索和标签检索支撑初期使用。
6. 当记忆规模和语义检索需求变大后，再加入向量检索。
7. 最后加入自动巩固、冲突修订、遗忘机制和多智能体共享记忆。

## 7. 与主流框架的关系

当前主流方案各有侧重：

- LangGraph / LangMem 强在工程分层和长期记忆工作流
- Mem0 强在用户、会话、组织等记忆分层和托管化接入
- Zep / Graphiti 强在 temporal knowledge graph
- Letta / MemGPT 强在 core memory、recall memory、archival memory 以及 agent 自编辑记忆
- LlamaIndex Memory 强在 memory blocks 和短长期记忆合并
- CrewAI Memory 强在多智能体场景、scope tree 和综合打分
- AutoGen Memory 强在协议化接口
- OpenAI Agents SDK Sessions 强在多轮会话历史管理

本项目不照搬某一家，而是吸收它们的共同趋势：

```text
分层记忆
+ 写入治理
+ 证据追踪
+ 混合检索
+ 反思巩固
+ 冲突修订
+ 遗忘机制
```

## 8. 最终形态

成熟后的记忆系统可以被看作一个 `Experience System`：

```text
观察现实
  -> 抽取经验
  -> 验证事实
  -> 结构化保存
  -> 定期反思
  -> 按任务检索
  -> 带证据使用
  -> 持续修订
```

也就是说，它不仅帮助智能体“记住”，更帮助智能体“更会做事”。
"# Memory" 
