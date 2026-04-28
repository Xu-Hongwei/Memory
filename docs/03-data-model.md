# 03. 数据模型

## 1. 设计目标

数据模型需要同时满足：

- 可检索
- 可解释
- 可验证
- 可修订
- 可审计
- 可迁移

因此建议采用：

```text
Event Log
+ Memory Item
+ Memory Version
+ Consolidation Candidate
+ Memory Entity
+ Memory Relation
+ Retrieval Log
```

## 2. Event Log

用于保存原始事件。

### 2.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 事件 ID |
| `event_type` | string | `user_message`、`tool_result`、`file_observation` 等 |
| `content` | text | 原始内容或摘要 |
| `source` | string | 来源 |
| `created_at` | datetime | 创建时间 |
| `sensitivity` | string | 敏感级别 |
| `metadata` | json | 额外字段 |

### 2.2 示例

```json
{
  "id": "evt_20260427_001",
  "event_type": "user_message",
  "content": "用户要求记忆系统宁可少记，也不要污染记忆。",
  "source": "conversation",
  "created_at": "2026-04-27T10:00:00+08:00",
  "sensitivity": "low",
  "metadata": {
    "conversation_id": "conv_001"
  }
}
```

## 10. Remote Adapter 数据结构

远程适配层不新增持久化表，当前只新增 API/CLI 返回结构：

```text
RemoteAdapterConfigRead
  configured
  base_url
  compatibility
  embedding_compatibility
  timeout_seconds
  api_key_configured
  llm_extract_path
  embedding_path
  health_path
  llm_model
  embedding_model

RemoteCandidateExtractionResult
  provider
  candidates: list[MemoryCandidateCreate]
  warnings
  metadata

RemoteCandidateImportResult
  provider
  candidates: list[MemoryCandidateRead]
  warnings
  metadata

RemoteCandidateEvaluationResult
  provider
  summary
  items
  warnings

RemoteCandidateEvaluationItem
  event_id / event_type / scope / source
  local_candidates
  remote_candidates
  local_types / remote_types / overlap_types
  local_only_types / remote_only_types
  remote_latency_ms
  remote_error

RemoteCandidateEvaluationSummary
  event_count
  remote_success_count / remote_error_count
  local_candidate_count / remote_candidate_count
  both_empty_event_count
  overlap_event_count
  local_only_event_count / remote_only_event_count
  divergent_event_count
  average_remote_latency_ms

RemoteEmbeddingRequest
  texts
  model
  metadata

RemoteEmbeddingResult
  provider
  vectors
  model
  dimensions
  metadata

MemoryEmbeddingRead
  memory_id
  model
  vector
  dimensions
  embedded_text
  created_at
  updated_at
```

重要约束：

- 远程候选复用 `MemoryCandidateCreate`，所以仍然必须满足本地候选记忆 schema。
- 远程候选默认不落库，不会自动生成 `memory_candidates`。
- 远程向量可以显式写入 `memory_embeddings`，作为本地 hybrid / semantic 检索的缓存。
- `memory_embeddings` 以 `(memory_id, model)` 作为主键，同一条记忆可以为不同 embedding 模型保存不同向量。
- 向量缓存只影响召回和排序，不会绕过 `status`、`scope`、`memory_type`、`confidence` 等本地治理。
- `RemoteAdapterConfigRead` 只暴露 `api_key_configured`，不暴露真实 token。

## 3. Memory Item

用于保存当前生效的长期记忆。

### 3.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 记忆 ID |
| `type` | string | 记忆类型 |
| `scope` | string | 适用范围 |
| `subject` | string | 记忆主题 |
| `content` | text | 记忆正文 |
| `status` | string | `active`、`stale`、`archived`、`rejected`、`superseded` |
| `confidence` | string | `confirmed`、`likely`、`inferred`、`unknown` |
| `source_event_ids` | json | 来源事件 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `last_used_at` | datetime | 最近使用时间 |
| `last_verified_at` | datetime | 最近验证时间 |
| `expires_at` | datetime | 过期时间 |
| `tags` | json | 标签 |
| `metadata` | json | 其他结构化字段 |

### 3.2 类型枚举

```text
user_preference
project_fact
tool_rule
environment_fact
troubleshooting
decision
workflow
reflection
```

### 3.3 范围设计

`scope` 建议采用层级结构：

```text
global
user:{user_id}
workspace:{workspace_id}
repo:{repo_path}
project:{project_id}
agent:{agent_id}
task:{task_id}
```

示例：

```text
global
repo:C:\Users\Administrator\Desktop\memory
project:memory-system
```

### 3.4 置信度

| 值 | 说明 |
| --- | --- |
| `confirmed` | 明确验证过 |
| `likely` | 很可能正确，但证据不完整 |
| `inferred` | 由模型推断，不应强依赖 |
| `unknown` | 未确认 |

长期记忆默认应该尽量只保存 `confirmed` 或高质量 `likely`。

## 4. Memory Version

用于保存记忆的历史版本。

### 4.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 版本 ID |
| `memory_id` | string | 所属记忆 |
| `version` | integer | 版本号 |
| `content` | text | 当时内容 |
| `change_type` | string | `create`、`update`、`merge`、`archive`、`stale`、`supersede` |
| `change_reason` | text | 变更原因 |
| `source_event_ids` | json | 证据 |
| `created_at` | datetime | 创建时间 |

### 4.2 设计理由

版本表用于避免直接覆盖历史，让系统能够回答：

- 这条记忆什么时候产生的
- 为什么后来被改了
- 新旧记忆有什么区别
- 是否可以回滚

## 5. Consolidation Candidate

用于保存“多条长期记忆可以被合并”的候选。它和普通 `MemoryCandidate` 不同：普通候选来自事件，巩固候选来自已有长期记忆。

### 5.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 巩固候选 ID |
| `source_memory_ids` | json | 待巩固的来源记忆 |
| `proposed_content` | text | 建议写入的新 consolidated 记忆 |
| `memory_type` | string | 巩固后的记忆类型 |
| `scope` | string | 巩固后的适用范围 |
| `subject` | string | 巩固后的主题 |
| `reason` | text | 为什么建议巩固 |
| `confidence` | string | 巩固后置信度 |
| `tags` | json | 合并后的标签 |
| `status` | string | `pending`、`committed`、`rejected` |
| `created_at` | datetime | 创建时间 |

### 5.2 设计约束

当前实现只自动提出满足以下条件的巩固候选：

- 来源记忆必须是 `active`。
- 来源记忆置信度必须是 `confirmed` 或 `likely`。
- 来源记忆必须拥有相同 `scope + memory_type + subject`。
- commit 后新记忆为 `active`，来源记忆变为 `superseded`。
- 来源记忆保留 `create -> supersede` 版本链。

这样做牺牲了一部分召回率，但能避免跨项目、跨类型或低置信记忆被过早总结。

## 6. Memory Entity

用于保存知识图谱里的实体。实体不是长期记忆本身，而是长期记忆里反复出现、可被关系连接的对象。

### 6.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 实体 ID |
| `name` | string | 实体名称 |
| `entity_type` | string | `repo`、`file`、`tool`、`command`、`error`、`solution` 等 |
| `scope` | string | 实体适用范围 |
| `aliases` | json | 别名、关键词或自然语言触发词 |
| `metadata` | json | 扩展字段 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### 6.2 示例

```json
{
  "name": "repo:C:/workspace/demo",
  "entity_type": "repo",
  "scope": "repo:C:/workspace/demo",
  "aliases": ["demo project", "当前项目"]
}
```

## 7. Memory Relation

用于表达实体和记忆之间的关系。

### 7.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 关系 ID |
| `from_id` | string | 起点 |
| `relation_type` | string | 关系类型 |
| `to_id` | string | 终点 |
| `confidence` | string | 置信度 |
| `source_memory_ids` | json | 这条关系来自哪些长期记忆 |
| `source_event_ids` | json | 来源 |
| `metadata` | json | 扩展字段 |

### 7.2 关系类型

```text
belongs_to
uses
depends_on
conflicts_with
supersedes
duplicates
derived_from
blocks
solves
has_start_command
defines_command
solved_by
```

### 7.3 设计约束

当前轻量图谱只把 `confirmed/likely` 关系用于强召回。`inferred/unknown` 可以保留为候选关系或弱信号，但不会直接注入上下文。

图谱召回还必须继续遵守长期记忆状态：

- `active` 记忆可以召回。
- `stale / archived / superseded` 记忆只保留审计，不作为当前事实注入。
- 当前 repo scope 不应该沿图谱串入其他 repo 的记忆。

图谱冲突检测基于同一属性的多目标关系：

```text
from_entity + relation_type -> target_entity_A
from_entity + relation_type -> target_entity_B
```

只有当这些关系都有 `active` 来源记忆，并且关系置信度是 `confirmed/likely` 时，才视为当前冲突。这样可以避免已经 superseded 的旧关系继续制造误报。

冲突解决不会由检测函数自动执行。系统会先生成 `Conflict Review Item`：

```text
conflict_key
scope
relation_type
from_entity_id
target_entity_ids
relation_ids
memory_ids
recommended_action
recommended_keep_memory_ids
status
```

review 被显式 resolve 后才会改变记忆状态：

- `accept_new`：保留推荐的新记忆，其他冲突记忆标记为 `superseded`。
- `keep_existing`：保留 review 中第一条当前事实，其他冲突记忆标记为 `superseded`。
- `keep_both_scoped`：确认两条事实都应保留，但需要靠 scope 或后续人工说明区分适用条件。
- `archive_all`：将冲突中的当前记忆全部归档。
- `ask_user`：标记为 `needs_user`，不改变记忆状态。

## 8. Retrieval Log

用于记录每次记忆检索。

### 8.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 检索 ID |
| `query` | text | 查询内容 |
| `task` | text | 任务文本 |
| `task_type` | string | 任务类型或召回意图 |
| `scope` | string | 适用范围 |
| `source` | string | 来源：`search / context / task_recall / graph_recall / manual` |
| `retrieved_memory_ids` | json | 召回或输入的记忆 |
| `used_memory_ids` | json | 返回给调用方或实际注入上下文的记忆 |
| `skipped_memory_ids` | json | 召回但未注入的记忆 |
| `warnings` | json | 低置信、预算截断、缺少验证时间等 warning |
| `feedback` | string | 人工或系统反馈：`useful / not_useful / mixed / unknown` |
| `feedback_reason` | text | 反馈原因 |
| `created_at` | datetime | 时间 |
| `feedback_at` | datetime | 反馈时间 |
| `metadata` | json | 排名分数等 |

### 8.2 作用

Retrieval Log 可以帮助优化：

- 哪些记忆经常被用到
- 哪些记忆从不被用到
- 哪些记忆检索相关但没有被采纳
- 哪些任务检索策略需要调整
- 哪些记忆虽然常被召回，但人工反馈认为没有帮助

### 8.3 使用统计与维护建议

`retrieval_logs` 可以聚合成每条记忆的使用统计：

| 字段 | 说明 |
| --- | --- |
| `retrieved_count` | 被召回次数 |
| `used_count` | 实际注入或返回给调用方的次数 |
| `skipped_count` | 召回后被上下文预算或策略跳过的次数 |
| `useful_feedback_count` | 相关日志被标记 useful 的次数 |
| `not_useful_feedback_count` | 相关日志被标记 not_useful 的次数 |
| `usage_score` | 简单聚合分数，用于排序维护队列 |
| `recommended_action` | `keep / review / mark_stale / archive` |
| `reasons` | 给出该建议的原因 |

第一版只给建议，不自动修改记忆状态：

- 多次 `not_useful` 的 active 记忆建议 `mark_stale`。
- 多次被召回但从未使用的 active 记忆建议 `review`。
- stale 记忆如果继续被检索但不用，或多次被认为没用，建议 `archive`。
- useful 反馈优先保护记忆，避免误删。

维护建议不会直接执行，而是先生成 `Maintenance Review Item`：

```text
memory_id
recommended_action
usage_score
retrieved_count / used_count / skipped_count
useful_feedback_count / not_useful_feedback_count
reasons
status
```

review resolve 后才会产生效果：

- `keep`：dismiss review，不改变记忆。
- `review`：标记为 `needs_user`，不改变记忆。
- `mark_stale`：调用生命周期接口，将 active 记忆标记为 stale。
- `archive`：调用生命周期接口，将记忆归档。

## 9. 排错经验结构

排错经验建议强制使用固定结构：

```text
问题：
经验：
解决方式：
证据：
适用范围：
```

示例：

```json
{
  "type": "troubleshooting",
  "scope": "repo:C:\\Users\\Administrator\\Desktop\\example",
  "subject": "Windows PowerShell 中文乱码",
  "content": {
    "问题": "在 PowerShell 中运行脚本后中文输出乱码。",
    "经验": "终端编码正常时，下一步应检查文件本身编码，而不是重复调整终端。",
    "解决方式": "先检查 chcp 和 PowerShell 编码，再用文件级读取确认源文件编码。",
    "证据": "已通过命令检查确认 code page 为 65001。",
    "适用范围": "Windows PowerShell 项目脚本调试"
  },
  "confidence": "confirmed"
}
```
