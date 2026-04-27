# 08. 主流记忆框架对比

## 1. 文档目的

本文用于记录当前主流智能体记忆框架的设计方向，并说明本项目应该借鉴什么、不应该照搬什么。

调研时间：2026-04-27。

注意：记忆框架发展很快，具体 API 和产品能力可能变化。实现前应重新检查官方文档。

## 2. 总体判断

主流方案正在从“聊天历史保存”演进到“可治理的长期经验系统”。

共同趋势包括：

- 短期记忆和长期记忆分层
- 用户、会话、组织、智能体等 scope 分层
- 写入和检索都带元数据
- 结合全文、向量、图谱和时间信息
- 允许后台巩固和摘要
- 支持多智能体或多工作流共享记忆
- 强调隐私、权限、审计和删除能力

本项目的目标不是复制某个框架，而是吸收这些趋势，形成一个 Python 优先、可解释、可治理的记忆核心。

## 3. 框架对比

| 框架 | 核心思路 | 值得借鉴 | 不直接照搬的原因 |
| --- | --- | --- | --- |
| LangGraph / LangMem | 将短期 state、长期 store、后台巩固和 agent workflow 结合 | 工程分层、namespace、后台 consolidation | 生态绑定较强，本项目先做独立核心 |
| Mem0 | AI memory layer，支持 conversation、session、user、organization 等层级 | scope 分层、托管和自托管思路、add/search/update/delete API | 直接接入快，但治理规则需要按本项目重新定义 |
| Zep / Graphiti | temporal knowledge graph，表达随时间变化的实体关系 | 时间图谱、事实有效期、实体关系演化 | 第一版图谱成本高，先用关系表模拟 |
| Letta / MemGPT | core memory、recall memory、archival memory，agent 可用工具编辑记忆 | 层级记忆、自编辑记忆、上下文窗口管理 | 直接让 agent 自编辑记忆风险较高，需要先有写入门禁 |
| LlamaIndex Memory | FIFO 短期记忆加 memory blocks，支持 fact extraction 和 vector blocks | memory block、优先级、短长期合并 | 更偏 LlamaIndex 生态组件，本项目需框架无关 |
| CrewAI Memory | 统一 Memory 类，LLM 推断 scope、category、importance，召回综合语义、时间和重要性 | scope tree、importance、recency、semantic 组合打分 | 自动 scope 推断容易带来不可控写入，MVP 应保守 |
| AutoGen Memory | Memory protocol，提供 add、query、update_context 等抽象 | 接口协议化，方便替换后端 | 它更像接口层，不足以定义完整治理系统 |
| OpenAI Agents SDK Sessions | session memory 自动保存和恢复多轮 conversation items | 会话连续性、SQLiteSession、历史压缩 | 主要解决对话历史，不等于完整长期记忆系统 |

## 4. 可借鉴设计

### 4.1 从 LangGraph / LangMem 借鉴

可借鉴：

- 短期上下文和长期记忆分开
- 按 namespace 管理长期记忆
- 后台任务做记忆巩固
- 记忆和 agent workflow 解耦

落地方式：

```text
scope = global / user / workspace / repo / agent / task
consolidation_jobs 定期处理重复、摘要和归档
```

### 4.2 从 Mem0 借鉴

可借鉴：

- conversation memory
- session memory
- user memory
- organization memory
- 简洁的 add/search/update/delete 操作

落地方式：

```text
conversation -> working memory
session -> task scope
user -> user_preference
organization -> shared policy or shared knowledge
```

本项目要额外强调：

- 写入前门禁
- 证据来源
- 冲突修订
- 敏感信息过滤

### 4.3 从 Zep / Graphiti 借鉴

可借鉴：

- temporal knowledge graph
- entity、edge、episode 的分层
- 关系有时间有效期
- 结合时间、全文、语义和图算法检索

落地方式：

第一版不直接上图数据库，而是用关系表模拟：

```text
memory_entities
memory_edges
memory_edge_versions
```

后续再升级：

```text
valid_from
valid_to
current_status
supersedes
```

### 4.4 从 Letta / MemGPT 借鉴

可借鉴：

- core memory：始终可见的关键记忆
- recall memory：可搜索的历史对话
- archival memory：长期语义存储
- agent 通过工具管理外部记忆

落地方式：

```text
core memory -> 高优先级、短小、稳定的上下文
recall memory -> Event Log 和会话摘要
archival memory -> Memory Item + 向量索引
```

但第一版不建议让 agent 直接无门禁写入长期记忆。应通过：

```text
propose_memory -> evaluate_candidate -> commit_memory
```

### 4.5 从 LlamaIndex Memory 借鉴

可借鉴：

- memory blocks
- static block
- fact extraction block
- vector block
- priority 控制上下文预算

落地方式：

```text
ContextBlock:
  priority
  memory_type
  content
  source
  confidence
```

### 4.6 从 CrewAI Memory 借鉴

可借鉴：

- scope tree
- semantic、recency、importance 综合打分
- read-only slice
- agent 私有记忆和共享记忆分开

落地方式：

```text
final_score =
  semantic_score
  + keyword_score
  + recency_score
  + importance_score
  + confidence_score
  - stale_penalty
```

MVP 阶段可以先不用 LLM 自动推断 scope，而是显式传入 scope。

### 4.7 从 AutoGen Memory 借鉴

可借鉴：

- 统一 memory protocol
- add/query/update_context 这样的最小接口
- 可替换后端

落地方式：

```python
class MemoryBackend:
    def add(self, item): ...
    def query(self, query): ...
    def compose_context(self, query): ...
```

### 4.8 从 OpenAI Agents SDK Sessions 借鉴

可借鉴：

- session 层自动保存多轮 conversation items
- SQLiteSession 适合本地开发
- 历史压缩适合控制上下文长度

落地方式：

```text
session_history 只解决当前会话连续性
long_term_memory 解决跨会话经验复用
```

这两者不要混淆。

## 5. 本项目推荐架构

综合主流框架后，本项目建议采用：

```text
Event Log
  -> Candidate Extractor
  -> Write Policy Gate
  -> Structured Memory Store
  -> FTS / Keyword Retrieval
  -> Optional Vector Retrieval
  -> Optional Temporal Graph
  -> Context Composer
  -> Consolidation Jobs
```

第一版核心：

```text
Python
+ Pydantic
+ SQLite
+ FTS5
+ pytest
```

第二版再加：

```text
FastAPI
+ background jobs
+ vector search
+ LLM extractor
```

第三版再加：

```text
temporal graph
+ multi-agent sharing
+ memory review UI
+ audit and export
```

## 6. 关键取舍

### 6.1 先规则，后模型

MVP 阶段优先使用规则和人工确认。模型可以辅助抽取候选，但不要直接决定长期写入。

### 6.2 先 FTS，后向量

早期很多记忆检索依赖精确内容，例如路径、命令、错误码、配置项。FTS 比向量更可控。

### 6.3 先结构化，后图谱

图谱很强，但第一版直接引入会增加复杂度。可以先用关系表模拟实体和关系。

### 6.4 先单智能体，后多智能体

多智能体共享记忆需要权限和冲突治理。第一版先把单智能体的写入和检索做稳。

## 7. 官方资料入口

- [LangChain Deep Agents Memory](https://docs.langchain.com/oss/python/deepagents/memory)
- [Mem0 Memory Types](https://docs.mem0.ai/core-concepts/memory-types)
- [Zep / Graphiti Overview](https://help.getzep.com/graphiti/graphiti/overview)
- [Zep Understanding the Graph](https://help.getzep.com/v2/understanding-the-graph)
- [Letta Agent Memory and Architecture](https://docs.letta.com/guides/agents/architectures/memgpt)
- [Letta Memory Management](https://docs.letta.com/concepts/memory-management)
- [LlamaIndex Memory](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/memory/)
- [CrewAI Memory](https://docs.crewai.com/en/concepts/memory)
- [AutoGen Memory and RAG](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/memory.html)
- [OpenAI Agents SDK Sessions](https://openai.github.io/openai-agents-python/sessions/)
