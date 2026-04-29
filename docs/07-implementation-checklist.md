# 07. Python 实施清单

## 1. MVP 技术选型

第一版建议明确采用 Python。

```text
语言：Python 3.11+
API：FastAPI
数据结构：Pydantic
数据库：SQLite
ORM：SQLAlchemy 或 SQLModel
全文检索：SQLite FTS5
测试：pytest
定时任务：APScheduler
向量检索：后续接 Qdrant / Chroma / LanceDB / pgvector
图谱：后续先用关系表模拟，再考虑 Kuzu / Neo4j / Graphiti
```

### 为什么 Python 起步

- 实现记忆治理逻辑更快
- Pydantic 对结构化输入输出很自然
- SQLite 和 FTS5 足够支撑 MVP
- 后续接模型抽取、embedding、向量库和后台任务都简单
- 更适合先验证“该不该记、怎么检索、怎么追溯”这些核心问题

### 暂不推荐第一版就做

- 不推荐一开始就全自动写入
- 不推荐一开始就依赖向量库
- 不推荐一开始就做复杂图数据库
- 不推荐同时维护 Python 和 TypeScript 两套核心实现

## 2. 初始目录结构

```text
memory-system/
  pyproject.toml
  README.md
  docs/
  src/
    memory_system/
      __init__.py
      config.py
      db.py
      models.py
      schemas.py
      event_log.py
      candidate_extractor.py
      write_policy.py
      memory_store.py
      retrieval.py
      context_composer.py
      consolidation.py
      api.py
  tests/
    test_event_log.py
    test_write_policy.py
    test_memory_store.py
    test_retrieval.py
    test_context_composer.py
  data/
    memory.sqlite
```

## 3. 推荐依赖

```toml
[project]
dependencies = [
  "fastapi",
  "uvicorn",
  "pydantic",
  "sqlalchemy",
  "aiosqlite",
  "apscheduler",
  "httpx",
]

[dependency-groups]
dev = [
  "pytest",
  "pytest-asyncio",
  "ruff",
]
```

如果想更快，可以先不接 FastAPI，只做本地 Python package。等核心函数稳定后再包 API。

## 4. 核心数据结构

### 4.1 Event

```python
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


EventType = Literal[
    "user_message",
    "assistant_message",
    "tool_result",
    "file_observation",
    "test_result",
    "user_confirmation",
]


class EventCreate(BaseModel):
    event_type: EventType
    content: str
    source: str
    scope: str = "global"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventRead(EventCreate):
    id: str
    created_at: datetime
```

### 4.2 MemoryCandidate

```python
from typing import Literal


MemoryType = Literal[
    "user_preference",
    "project_fact",
    "tool_rule",
    "environment_fact",
    "troubleshooting",
    "decision",
    "workflow",
    "reflection",
]

Confidence = Literal["confirmed", "likely", "inferred", "unknown"]
Risk = Literal["low", "medium", "high"]


class MemoryCandidateCreate(BaseModel):
    content: str
    memory_type: MemoryType
    scope: str
    subject: str
    source_event_ids: list[str]
    reason: str
    confidence: Confidence = "unknown"
    risk: Risk = "low"
```

### 4.3 PolicyDecision

```python
PolicyAction = Literal["write", "reject", "ask_user", "merge", "update"]


class PolicyDecisionRead(BaseModel):
    id: str
    candidate_id: str
    decision: PolicyAction
    reason: str
    matched_memory_ids: list[str] = Field(default_factory=list)
    required_action: str | None = None
```

### 4.4 MemoryItem

```python
MemoryStatus = Literal["active", "stale", "archived", "rejected", "superseded"]


class MemoryItemCreate(BaseModel):
    content: str
    memory_type: MemoryType
    scope: str
    subject: str
    confidence: Confidence
    source_event_ids: list[str]
    tags: list[str] = Field(default_factory=list)


class MemoryItemRead(MemoryItemCreate):
    id: str
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None
    last_verified_at: datetime | None = None
```

## 5. 数据库表清单

第一阶段建议建这些表：

```text
events
memory_candidates
policy_decisions
memory_items
memory_versions
consolidation_candidates
memory_entities
memory_relations
retrieval_logs
```

第二阶段再加：

```text
memory_embeddings
consolidation_jobs
memory_feedback
memory_edges
```

当前 `memory_embeddings` 已经进入实现：本地使用 `(memory_id, model)` 缓存远程 embedding 向量，`search_memory` 支持 `retrieval_mode=semantic|hybrid`，远程 API / CLI 可以显式为单条记忆或一批缺失记忆建立向量缓存，并能用 v1/v2/cn/public fixture 和 category summary 对比 keyword / semantic / hybrid / guarded_hybrid，以及可选的 `llm_guarded_hybrid` / `selective_llm_guarded_hybrid` 召回表现。

## 6. SQLite FTS5

MVP 阶段建议对 `memory_items` 建 FTS 表。

```sql
CREATE VIRTUAL TABLE memory_items_fts USING fts5(
  subject,
  content,
  tags,
  content='memory_items',
  content_rowid='rowid'
);
```

注意：

- 文件路径、命令、错误码、函数名优先走 FTS
- 用户偏好和排错经验可以先走 FTS，再加规则重排
- 向量检索后续只作为召回通道之一

## 7. 核心接口

### 7.1 record_event

记录原始事件。

```python
def record_event(input: EventCreate) -> EventRead:
    ...
```

要求：

- 必须生成稳定事件 ID
- 必须记录 created_at
- 必须进行敏感信息检查
- 必须保留 scope 和 source

### 7.2 propose_memory

从事件中抽取候选记忆。

```python
def propose_memory(event_id: str) -> list[MemoryCandidateCreate]:
    ...
```

MVP 可以先用规则实现：

- 用户明确说“以后”“默认”“记住”时，生成偏好候选
- 工具结果确认路径、命令、配置时，生成项目事实候选
- 排错成功后，生成 troubleshooting 候选

后续再接 LLM 抽取。

### 7.3 evaluate_candidate

执行写入门禁。

```python
def evaluate_candidate(candidate_id: str) -> PolicyDecisionRead:
    ...
```

判断内容：

- 是否长期有用
- 是否明确真实
- 是否敏感
- 是否有复用价值
- 是否重复
- 是否冲突

### 7.4 commit_memory

写入长期记忆。

```python
def commit_memory(candidate_id: str, decision_id: str) -> MemoryItemRead:
    ...
```

要求：

- 只有 `write`、`merge`、`update` 决策可以进入提交
- 每次写入都要生成 `memory_versions`
- 每次写入都要保留来源事件
- 更新 FTS 索引

### 7.5 search_memory

检索记忆。

```python
class SearchMemoryInput(BaseModel):
    query: str
    task_type: str | None = None
    memory_types: list[MemoryType] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    limit: int = 10


def search_memory(input: SearchMemoryInput) -> list[MemoryItemRead]:
    ...
```

MVP 排序建议：

```text
final_score =
  keyword_score
  + scope_score
  + confidence_score
  + recency_score
  - stale_penalty
```

### 7.6 compose_context

组装可注入上下文。

```python
class ContextBlock(BaseModel):
    content: str
    memory_ids: list[str]
    warnings: list[str] = Field(default_factory=list)


def compose_context(task: str, memories: list[MemoryItemRead], token_budget: int) -> ContextBlock:
    ...
```

要求：

- 只注入当前任务相关记忆
- 标注置信度和来源
- 标记可能过期的事实
- 不注入敏感内容
- 不注入冲突未解决的内容

### 7.7 consolidate

执行记忆巩固。

```python
def propose_consolidations(
    scope: str | None = None,
    memory_type: MemoryType | None = None,
    min_group_size: int = 2,
) -> list[ConsolidationCandidateRead]:
    ...


def commit_consolidation(candidate_id: str, reason: str | None = None) -> MemoryItemRead:
    ...
```

当前 MVP 先只做保守巩固：

- 只选择 `active` 且 `confirmed/likely` 的记忆。
- 只合并同 `scope + memory_type + subject` 的记忆。
- 先生成巩固候选，不直接改写长期记忆。
- commit 后生成新 consolidated 记忆。
- 来源记忆标记为 `superseded`，并保留版本链。

后续再加入：

- 语义相似聚类。
- LLM 辅助摘要。
- 长时间未使用记忆的归档建议。
- 人工 review 队列和 CLI 审查入口。

## 8. FastAPI 路由

```text
POST /events
GET  /events/{event_id}

POST /candidates/from-event/{event_id}
GET  /candidates/{candidate_id}

POST /policy/evaluate/{candidate_id}

POST /memories/commit
GET  /memories/{memory_id}
GET  /memories/search
GET  /retrieval/logs
GET  /retrieval/logs/{log_id}
POST /retrieval/logs/{log_id}/feedback
GET  /memories/usage
GET  /memories/{memory_id}/usage
POST /maintenance/reviews/from-usage
GET  /maintenance/reviews
GET  /maintenance/reviews/{review_id}
POST /maintenance/reviews/{review_id}/resolve
PATCH /memories/{memory_id}
POST /memories/{memory_id}/stale
POST /memories/{memory_id}/archive
POST /memories/{memory_id}/supersede

POST /context/compose
POST /recall/task
POST /recall/orchestrated
POST /recall/graph
POST /graph/entities
GET  /graph/entities
POST /graph/relations
GET  /graph/relations
GET  /graph/conflicts
POST /graph/conflict-reviews/from-conflicts
GET  /graph/conflict-reviews
GET  /graph/conflict-reviews/{review_id}
POST /graph/conflict-reviews/{review_id}/resolve
POST /consolidation/propose
GET  /consolidation/candidates
POST /consolidation/{candidate_id}/commit
POST /consolidation/{candidate_id}/reject
```

API 第一版不需要复杂权限，但要预留：

- `user_id`
- `agent_id`
- `workspace_id`
- `repo_path`

## 8.1 CLI 审查入口

冲突审查第一版先提供命令行入口，避免一开始就把复杂度放到 Web UI：

```text
memoryctl reviews generate
memoryctl reviews list
memoryctl reviews show <review_id>
memoryctl reviews resolve <review_id> --action accept_new
memoryctl reviews resolve <review_id> --action keep_existing
memoryctl reviews resolve <review_id> --action keep_both_scoped
memoryctl reviews resolve <review_id> --action ask_user
memoryctl reviews resolve <review_id> --action archive_all
memoryctl maintenance generate
memoryctl maintenance list
memoryctl maintenance show <review_id>
memoryctl maintenance resolve <review_id> --action mark_stale
memoryctl maintenance resolve <review_id> --action archive
```

验收标准：

- 可以从当前 graph conflict 生成 pending review。
- 可以按 status、scope、relation_type 列出 review。
- `show` 能看到冲突实体、目标实体、关系和来源记忆。
- `resolve` 后记忆生命周期状态与 API 行为一致。
- 支持 `--json`，方便后续接 Web UI 或脚本。

## 8.2 Remote Adapter 调试入口

远程阶段先做可替换 adapter，不直接把远程结果写入长期记忆。

代码：

```text
src/memory_system/remote.py
tests/test_remote_adapters.py
```

环境变量：

```text
MEMORY_REMOTE_BASE_URL
MEMORY_REMOTE_API_KEY
MEMORY_REMOTE_TIMEOUT_SECONDS
MEMORY_REMOTE_LLM_EXTRACT_PATH
MEMORY_REMOTE_EMBEDDING_PATH
MEMORY_REMOTE_HEALTH_PATH
```

API：

```text
GET  /remote/status
GET  /remote/health
POST /remote/route
POST /remote/extract/{event_id}
POST /remote/evaluate-candidates
POST /candidates/from-event/{event_id}/remote
POST /remote/embed
```

CLI：

```text
memoryctl remote status
memoryctl remote health
memoryctl remote route --event-id <event_id>
memoryctl remote extract <event_id>
memoryctl remote evaluate --event-id <event_id>
memoryctl remote import <event_id>
memoryctl remote embed "memory text"
```

验收标准：

- `remote status` 不泄露 API key。
- `remote route` 返回长期候选、短期会话记忆、忽略项、拒绝项和待确认项；长期候选只进入 pending，不自动 commit。
- `remote extract` 返回 `RemoteCandidateExtractionResult`。
- `remote evaluate` 返回 `RemoteCandidateEvaluationResult`，不写候选表。
- `remote import` 返回 `RemoteCandidateImportResult`，作为 legacy long-term-only 入口只创建 pending candidate。
- `remote embed` 返回向量数量和维度。
- `remote extract` 不会写入 `memory_candidates`。
- 远程候选导入后仍然必须走 `evaluate_candidate` 和 `commit_memory`。
- 远程错误以清晰的 502/503 或 CLI 错误返回。

## 9. MVP 开发顺序

### Step 1：事件日志

- 创建 SQLite 数据库
- 建 `events` 表
- 实现 `record_event`
- 写入和读取测试

### Step 2：候选记忆

- 建 `memory_candidates` 表
- 实现候选记忆结构
- 先用规则或手动输入生成候选
- 不做自动写入

### Step 3：写入门禁

- 实现敏感信息检查
- 实现重复搜索
- 实现冲突检测占位
- 输出 `write / reject / ask_user / merge / update`

### Step 4：长期记忆

- 建 `memory_items`
- 建 `memory_versions`
- 实现 `commit_memory`
- 每次写入必须有来源事件

### Step 5：检索

- 建 FTS 索引
- 支持按类型、范围、关键词检索
- 实现基础排序

### Step 6：上下文组装

- 根据任务类型选择记忆
- 控制注入长度
- 标记置信度和来源

### Step 7：巩固任务

- 生成 consolidation candidate
- commit 后写入 consolidated 记忆
- 将来源记忆标记为 superseded
- 验证旧记忆不再参与默认检索
- 后续再加入低价值归档和反思型记忆

### Step 8：轻量知识图谱

- 建 `memory_entities`
- 复用/扩展 `memory_relations`
- 支持 repo、file、tool、command、error、solution 等实体
- 支持从关系挂载 `source_memory_ids`
- 实现 `graph_recall_for_task`
- 验证图谱召回仍遵守 scope、status 和 confidence

### Step 9：图谱冲突检测

- 按 `from_entity + relation_type` 分组关系
- 如果同组关系指向多个不同 target，生成冲突结果
- 只使用 `confirmed/likely` 关系
- 只使用仍然 `active` 的来源记忆
- 验证同目标重复关系不误报

### Step 10：冲突解决工作流

- 将 graph conflict 转成 conflict review item
- 为 review 生成推荐动作和推荐保留记忆
- 支持 `accept_new`
- 支持 `keep_existing`
- 支持 `keep_both_scoped`
- 支持 `archive_all`
- 支持 `ask_user`
- resolve 后写入记忆版本链

## 10. 测试用例

### 10.1 不应写入一次性请求

输入：

```text
帮我把这句话改得更正式一点。
```

期望：

```text
reject: 一次性请求，无长期复用价值。
```

### 10.2 应写入用户长期偏好

输入：

```text
以后类似项目说明默认用中文写，并且区分事实和推断。
```

期望：

```text
write or ask_user: 用户长期偏好，scope=global/user。
```

### 10.3 应写入项目事实

输入：

```text
工具读取 package.json 后确认 dev 脚本为 vite --host 0.0.0.0。
```

期望：

```text
write: 已由文件观察验证，scope=repo。
```

### 10.4 不应写入未验证猜测

输入：

```text
看起来这个项目可能用了 Redis。
```

期望：

```text
reject or pending: 未验证猜测。
```

### 10.5 冲突更新

已有记忆：

```text
项目启动命令是 npm run dev。
```

新观察：

```text
用户明确说明现在改为 pnpm dev，并且 package.json 已验证。
```

期望：

```text
update: 旧记忆标记为 superseded，新记忆 active。
```

### 10.6 排错经验写入

输入：

```text
问题真实发生：构建失败。
原因确认：缺少环境变量 API_BASE_URL。
解决方式验证：设置变量后构建通过。
```

期望：

```text
write: troubleshooting，包含问题、经验、解决方式。
```

### 10.7 自动巩固

已有记忆：

```text
用户偏好：技术文档默认用中文。
用户偏好：回答时区分事实和推断。
scope=global, memory_type=user_preference, subject=文档风格。
```

期望：

```text
propose_consolidations: 生成 1 条巩固候选。
commit_consolidation: 新 consolidated 记忆 active，两个来源记忆 superseded。
search_memory: 只返回 consolidated 记忆。
```

### 10.8 图谱召回

已有实体和关系：

```text
repo:C:/workspace/demo -> has_start_command -> pnpm dev
关系来源记忆：项目启动命令是 pnpm dev。
```

输入：

```text
这个项目启动失败了，帮我排查。
scope=repo:C:/workspace/demo
```

期望：

```text
graph_recall_for_task: 匹配当前 repo 实体，沿 has_start_command 关系召回启动命令记忆。
如果来源记忆已经 superseded，或者关系 confidence=inferred，则不注入上下文。
```

### 10.9 图谱冲突检测

已有关系：

```text
repo:C:/workspace/demo -> has_start_command -> npm run dev
repo:C:/workspace/demo -> has_start_command -> pnpm dev
```

期望：

```text
detect_graph_conflicts: 返回 1 条冲突。
from_entity 是当前 repo。
relation_type 是 has_start_command。
target_entities 包含 npm run dev 和 pnpm dev。
如果其中一条关系只来自 stale/superseded 记忆，则不报冲突。
```

### 10.10 冲突解决

已有 review：

```text
repo -> has_start_command -> npm run dev
repo -> has_start_command -> pnpm dev
recommended_action=accept_new
recommended_keep_memory=pnpm dev 记忆
```

期望：

```text
resolve_conflict_review(action=accept_new)
旧 npm run dev 记忆 superseded
新 pnpm dev 记忆 active
同一个 graph conflict 不再出现
```

## 11. 关键风险

### 11.1 过度自动写入

风险：

- 临时信息进入长期记忆
- 用户一次性表达被当成永久偏好

缓解：

- 早期使用候选池和人工确认
- 对用户偏好设置更高写入门槛

### 11.2 向量检索误召回

风险：

- 召回语义相似但事实不相关的记忆

缓解：

- 向量检索只做召回，不直接注入
- 结合 scope、type、confidence 重排序

### 11.3 旧事实污染

风险：

- 旧项目路径、旧启动命令、旧配置继续被使用

缓解：

- 引入 `last_verified_at`
- 对易变事实设置 `expires_at`
- 使用前重新验证高风险事实

### 11.4 敏感信息残留

风险：

- 密钥、账号、私密内容被长期保存

缓解：

- 写入前敏感扫描
- Event Log 脱敏
- 支持用户删除和导出

## 12. 第一版成功标准

第一版不需要“很聪明”，但必须可靠。

成功标准：

- 能记录事件
- 能提出候选记忆
- 能拒绝明显不该写入的信息
- 能写入有证据的长期记忆
- 能按类型和范围检索
- 能输出带置信度的上下文
- 能追溯记忆来源
- 能用 pytest 固定关键行为

只要做到这些，后续加入向量检索、反思巩固和多智能体共享才有稳定基础。
