# 06. 演进路线

## 1. 总体路线

记忆系统建议从保守、可验证的 Python MVP 开始，再逐步加入自动化、向量检索、图谱、反思巩固和多智能体共享能力。

推荐路线：

```text
Phase 0: 需求边界和写入规则
Phase 1: Python Event Log MVP
Phase 2: 结构化长期记忆
Phase 3: API 和本地 SDK
Phase 4: 混合检索
Phase 5: 反思巩固
Phase 6: 冲突、遗忘和治理
Phase 7: Temporal Graph Memory
Phase 8: 多智能体共享记忆
Phase 9: Experience System
```

这条路线的重点是先把“不会乱记”做好，再追求“记得更多”和“检索更聪明”。

## 2. Phase 0：需求边界和写入规则

### 目标

明确系统到底要记什么、不记什么，以及记忆如何被使用。

### 关键产物

- 记忆类型定义
- 写入规则
- 敏感信息策略
- 用户可见的记忆管理方式
- 删除和导出策略
- 当前项目是否允许自动写入的开关

### 验收标准

- 能清楚区分临时上下文和长期记忆
- 能清楚区分事实、偏好、经验和推断
- 有明确的“不写入”规则
- 有明确的冲突处理策略

## 3. Phase 1：Python Event Log MVP

### 目标

先把原始事件安全记录下来，为后续抽取和回放打基础。

### 推荐技术

```text
Python
+ Pydantic
+ SQLite
+ pytest
```

### 功能

- 记录用户消息摘要
- 记录工具调用结果摘要
- 记录文件观察结果摘要
- 记录事件时间、来源和作用域
- 支持按时间、来源和 task_id 查询
- 对敏感字段做脱敏或拒绝记录

### 暂不做

- 不做自动长期记忆写入
- 不做向量检索
- 不做模型自动总结

### 验收标准

- 能查到某次事件发生过
- 能追溯某条候选记忆来自哪里
- 敏感信息不会原样进入日志
- 测试覆盖事件写入、读取、脱敏和异常输入

## 4. Phase 2：结构化长期记忆

### 目标

建立可治理的长期记忆库。

### 推荐技术

```text
SQLite
+ SQLAlchemy 或 SQLModel
+ Pydantic schemas
+ SQLite FTS5
```

### 功能

- 新增 Memory Item
- 新增 Memory Version
- 新增 Memory Relation
- 新增 Memory Candidate
- 新增 Policy Decision
- 支持类型、范围、置信度、状态和来源事件
- 支持人工确认写入

### 验收标准

- 可以写入一条项目事实
- 可以写入一条用户偏好
- 可以写入一条排错经验
- 可以通过类型和范围检索
- 可以查看来源证据
- 可以将旧记忆标记为 `stale`、`archived` 或 `superseded`

## 5. Phase 3：API 和本地 SDK

### 目标

把记忆核心封装成可被 Agent 调用的服务。

### 推荐技术

```text
FastAPI
+ Pydantic
+ Uvicorn
+ httpx
```

### API 能力

- `POST /events`
- `POST /candidates`
- `POST /policy/evaluate`
- `POST /memories`
- `GET /memories/search`
- `POST /context/compose`
- `POST /consolidation/propose`
- `GET /consolidation/candidates`
- `POST /consolidation/{candidate_id}/commit`
- `POST /consolidation/{candidate_id}/reject`

### 本地 SDK 能力

```python
client.record_event(...)
client.propose_memory(...)
client.evaluate_candidate(...)
client.commit_memory(...)
client.search_memory(...)
client.compose_context(...)
```

### 验收标准

- Agent 可以通过 HTTP 或 Python SDK 调用记忆系统
- API 返回结构稳定
- 错误响应可测试
- 每次写入都有审计记录

## 6. Phase 4：混合检索

### 目标

让系统根据任务类型召回合适记忆。

### 检索通道

```text
Keyword / BM25
FTS5
Scope filter
Type filter
Recency score
Confidence score
Vector search
Graph search
```

### 推荐路线

早期：

```text
SQLite + FTS5 + 规则排序
```

中期：

```text
SQLite + sqlite-vec
```

或：

```text
Qdrant / Chroma / LanceDB
```

后期：

```text
PostgreSQL + pgvector
```

### 验收标准

- 排错任务能召回相关排错经验
- 项目任务能优先召回当前 repo 记忆
- 用户偏好不会淹没项目事实
- 过期记忆会被标记或降权
- 向量检索只做召回，不直接决定注入结果

## 7. Phase 5：反思巩固

### 目标

从多个事件和记忆中总结更高层经验。

### 推荐技术

```text
APScheduler
+ 后台任务队列
+ LLM summarizer
+ pytest snapshot tests
```

### 功能

- 定期扫描 Event Log
- 合并重复记忆
- 从多次排错中提炼经验
- 生成 reflection 类型记忆
- 更新 reuse_count 和 last_used_at
- 将低置信候选保留在 pending 状态

当前实现已经先落地规则版最小闭环：按 `scope + memory_type + subject` 分组，生成巩固候选，commit 后写入 consolidated 记忆，并把来源记忆标记为 `superseded`。LLM summarizer、语义聚类和后台调度仍属于后续增强。

检索使用日志也已经落地第一版：`search / context / task_recall / graph_recall` 会写入 `retrieval_logs`，并支持对单次检索写入 useful、not_useful、mixed 或 unknown 反馈。当前已经可以基于这些日志生成 `keep / review / mark_stale / archive` 维护建议，并转成可审查的 maintenance review item；后续的 reuse score、降权和遗忘策略应继续优先基于这些日志，而不是只看静态字段。

### 巩固触发

- 每 N 次对话
- 每个项目任务完成后
- 每次排错成功后
- 用户手动触发
- 定时任务

### 验收标准

- 多条相似记忆能合并
- 旧的临时信息不会变成长期事实
- 反思型记忆有明确来源
- 反思结果不会自动覆盖 confirmed 记忆

## 8. Phase 6：冲突、遗忘和治理

### 目标

让系统长期运行后仍然保持干净。

当前实现先加入了 Phase 6-lite：轻量知识图谱层。它还不是 temporal graph database，而是在 SQLite 中增加 `memory_entities` 和可挂载来源记忆的 `memory_relations`，用于验证实体关系对召回是否真的有帮助。

随后补上了冲突审查层：图谱只负责发现“同一实体同一属性出现多个当前值”，真正改变长期记忆状态必须先生成 `conflict_review_item`，再显式执行 resolve 动作。

### 功能

- 冲突检测
- 版本修订
- 记忆归档
- 过期提醒
- 删除和导出
- 用户可查看记忆
- 记忆使用日志
- 轻量实体和关系召回

### Phase 6-lite 已实现能力

- 保存 repo、file、tool、command、error、solution 等实体。
- 保存实体关系，并记录 `source_memory_ids`。
- 从任务文本和当前 scope 匹配 seed entities。
- 沿 confirmed/likely 关系召回相关 active 记忆。
- 防止其他 repo、旧记忆和低置信关系串入上下文。
- 检测同一实体同一关系类型指向多个不同目标的当前事实冲突。
- 将图谱冲突转成待审查项，并通过 `accept_new / keep_existing / keep_both_scoped / ask_user / archive_all` 治理冲突记忆。
- 记录检索、上下文注入和召回使用情况，为排序和遗忘提供反馈数据。
- 将低使用或负反馈记忆转成 maintenance review，并通过显式 resolve 执行 stale/archive。

## 8.1 Phase 6.5：远程适配器

### 目标

在不改变本地写入治理的前提下，接入远程 LLM 和远程 embedding 服务，验证真实模型能力是否能提高候选记忆提取和语义表示质量。

### 当前已实现能力

- `RemoteAdapterConfig` 从环境变量读取远程地址、token、超时和路径配置。
- `RemoteLLMClient.extract_candidates(...)` 调用远程 `/memory/extract`，返回结构化候选记忆。
- `RemoteEmbeddingClient.embed_texts(...)` 调用远程 `/embeddings`，返回向量。
- FastAPI 暴露 `/remote/status`、`/remote/health`、`/remote/extract/{event_id}`、`/remote/embed`。
- CLI 暴露 `memoryctl remote status/health/extract/embed`。
- 远程候选默认 dry-run，不自动进入 `memory_candidates`。

### 验收标准

- 远程服务不可用时，本地核心记忆流程不受影响。
- 远程候选必须能被 Pydantic schema 校验。
- API key 不出现在 status 输出、日志或 CLI JSON 中。
- 同一批 event 可以同时跑本地规则和远程提取，方便比较召回率与误写风险。
- 写入长期记忆仍必须经过本地 `evaluate_candidate`。

### 遗忘机制

记忆可以因为以下原因被降权或归档：

- 长期未使用
- 已被新版本替代
- 来源不可靠
- 适用范围不再存在
- 用户明确要求删除
- 被验证为错误

### 验收标准

- 新偏好可以替代旧偏好
- 旧项目事实可以被标记为过期
- 用户可以查看和删除记忆
- 系统不会使用已归档记忆作为当前事实

## 9. Phase 7：Temporal Graph Memory

### 目标

引入类似 Zep / Graphiti 的时间知识图谱能力，让系统能表达“关系在某段时间内成立”。

### 适合保存

- 用户角色变化
- 项目依赖变化
- 工具规则变化
- 组织关系变化
- 历史决策和后续修订

### 数据表达

```text
subject
predicate
object
valid_from
valid_to
source_event_ids
confidence
status
```

### 技术选择

早期可以继续用关系表模拟图谱：

```text
memory_entities
memory_edges
memory_edge_versions
```

后期再考虑：

```text
Neo4j
Kuzu
PostgreSQL graph tables
Graphiti
```

### 验收标准

- 同一实体可以保留历史关系
- 当前事实和历史事实能区分
- 检索时默认使用当前有效关系
- 用户可以查询“过去为什么这么做”

## 10. Phase 8：多智能体共享记忆

### 目标

支持多个智能体共享部分记忆，同时保留各自边界。

### 分层

```text
agent_private_memory
team_shared_memory
project_memory
global_policy_memory
```

### 关键问题

- 哪些记忆可以共享
- 哪些记忆只属于某个智能体
- 共享记忆如何审批
- 冲突由谁解决
- 全局规则如何优先于个体经验

### 验收标准

- 不同智能体能共享项目事实
- 个体偏好不会错误传播到全局
- 全局安全规则优先级最高
- 共享记忆有读写权限控制

## 11. Phase 9：Experience System

### 目标

把记忆系统升级为智能体的经验系统。

### 能力

- 从经验中学习流程
- 识别重复问题
- 主动建议规则更新
- 对旧经验做再验证
- 根据任务动态选择记忆策略
- 形成项目级、团队级、用户级知识资产

### 最终形态

```text
Experience System =
  Event Log
  + Memory Governance
  + Structured Knowledge
  + Semantic Retrieval
  + Reflection
  + Temporal Graph
  + Forgetting
  + Audit
  + User Control
```
