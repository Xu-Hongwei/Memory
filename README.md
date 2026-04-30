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

已实现 Phase 1 到 Phase 6-lite 的本地 MVP，并加入了检索使用日志和 Recall Orchestrator：

```text
src/memory_system/
  schemas.py        Pydantic 事件、候选记忆、长期记忆和检索结构
  event_log.py      SQLite 事件日志、查询和基础敏感信息处理
  memory_store.py   结构化候选记忆、写入门禁、长期记忆、版本记录和 FTS 检索
  context_composer.py  检索记忆的上下文组装和预算控制
  remote.py         Remote LLM / embedding HTTP adapter、记忆分流和召回 planner
  session_memory.py 会话级短期记忆、短期上下文组装和本地兜底筛选
  recall_orchestrator.py  统一召回编排层
  graph_recall.py   轻量知识图谱召回
  cli.py            conflict review 的命令行审查入口
  api.py            FastAPI 接口层
tests/
  test_cli.py
  test_api.py
  test_remote_adapters.py
  test_event_log.py
  test_memory_store.py
  test_golden_write_policy.py
  test_golden_retrieval_context.py
  test_golden_lifecycle.py
  test_golden_task_recall.py
  test_golden_consolidation.py
  test_golden_graph_recall.py
  test_golden_graph_conflicts.py
  test_golden_conflict_reviews.py
  test_golden_session_closeout.py
  test_lifecycle.py
  test_task_recall.py
  test_recall_orchestrator.py
  test_consolidation.py
  test_memory_graph.py
  test_graph_conflicts.py
  test_review_and_context.py
  fixtures/golden_cases/generate_write_policy.py
  fixtures/golden_cases/write_policy.jsonl
  fixtures/golden_cases/generate_retrieval_context.py
  fixtures/golden_cases/retrieval_context.jsonl
  fixtures/golden_cases/generate_lifecycle.py
  fixtures/golden_cases/lifecycle.jsonl
  fixtures/golden_cases/generate_task_recall.py
  fixtures/golden_cases/task_recall.jsonl
  fixtures/golden_cases/generate_consolidation.py
  fixtures/golden_cases/consolidation.jsonl
  fixtures/golden_cases/generate_graph_recall.py
  fixtures/golden_cases/graph_recall.jsonl
  fixtures/golden_cases/generate_graph_conflicts.py
  fixtures/golden_cases/graph_conflicts.jsonl
  fixtures/golden_cases/generate_conflict_reviews.py
  fixtures/golden_cases/conflict_reviews.jsonl
  fixtures/golden_cases/generate_session_closeout.py
  fixtures/golden_cases/session_closeout.jsonl
```

候选记忆已经不只是关键词触发，而是会保留结构化分析：

```text
claim
evidence_type
time_validity
reuse_cases
scores.long_term / evidence / reuse / risk / specificity
```

写入门禁会基于这些结构化字段输出 `structured_reason`，再决定 `write / reject / ask_user / merge / update`。

Phase 5 先实现了一个保守的规则版自动巩固：

- 只巩固 `active` 且 `confidence` 为 `confirmed/likely` 的记忆。
- 只把同 `scope + memory_type + subject` 的记忆归为一组。
- 先生成 `consolidation_candidate`，不直接改写长期记忆。
- 人工或 API commit 后，生成一条新的 consolidated 记忆，并把来源记忆标记为 `superseded`。
- 巩固过程会写入 `memory_versions`，旧记忆退出默认检索，但历史可追溯。

Phase 6-lite 先实现轻量知识图谱：

- `memory_entities` 保存 repo、file、tool、command、error、solution 等实体。
- `memory_relations` 保存实体之间的关系，并可挂载 `source_memory_ids`。
- `graph_recall_for_task(...)` 会从任务文本和当前 scope 找 seed entities，再沿 confirmed/likely 关系召回相关记忆。
- 图谱召回仍然尊重 `active` 状态和 scope 边界，旧记忆和低置信关系不会强行注入上下文。
- `detect_graph_conflicts(...)` 会检测同一实体的同一种关系是否指向多个不同目标，例如同一个 repo 同时存在两个启动命令。
- `create_conflict_reviews(...)` 和 `resolve_conflict_review(...)` 会把冲突转成待审查项，并支持 `accept_new / keep_existing / keep_both_scoped / ask_user / archive_all` 等解决动作。

Recall Orchestrator 现在作为智能体接入记忆的推荐入口：

- `orchestrate_recall(...)` 会先判断当前任务是否值得召回记忆，像 `ok` / `谢谢` 这类低记忆需求消息会直接跳过。
- 召回计划先由 planner 生成：有 remote LLM 时优先调用 `RemoteLLMClient.plan_recall(...)`，失败时回退到本地 `RecallPlanner`。
- planner 会输出 `query_terms`、`memory_types`、`scopes`、`strategy_hint`、`include_graph`、`include_session`、`needs_llm_judge` 和置信度等字段。
- `strategy="auto"` 会综合 planner 的策略建议和当前可用客户端：没有 remote embedding 时降级为 keyword；有 embedding 时可走 `guarded_hybrid`；同时有 LLM 且需要复核时可走 `selective_llm_guarded_hybrid`。
- 图谱召回需要调用方 `include_graph=true` 且 planner `include_graph=true`；短期记忆只要调用方允许就会查，但 planner 不建议 session 时会把本轮 session 召回软限制到 1 条。
- 可选合并图谱召回和当前 session memory；最终仍然统一经过 `active`、scope、confidence、token budget 和 no-match 保护。
- 每次编排都会写入 `retrieval_logs(source=orchestrated_recall)`，记录 retrieved / used / skipped / warnings / steps / planner metadata，方便后续做反馈、调参和遗忘。

黄金测试集当前是 2000 条固定回归样本，由 `tests/fixtures/golden_cases/generate_write_policy.py`
生成并写入 `tests/fixtures/golden_cases/write_policy.jsonl`。样本不是复制网络语料，而是参考主流记忆框架的分层共识后改写出的日常交流、工程协作和排错场景。

当前覆盖：

```text
长期偏好正例：300
日常喜欢表达反例：140
临时状态反例：170
已验证项目事实：180
工具/流程规则：140
已验证排错经验：150
敏感信息反例：120
低证据推断：120
重复事实合并：110
冲突事实复核：110
普通/未验证交流反例：160
纯提问反例：80
情绪/闲聊反例：80
显式 workflow：70
显式 environment_fact：70
```

这批样本已经推动了两处策略收紧：

- `喜欢` 只有同时指向回答、文档、代码、语言、格式等可复用对象时才进入长期偏好候选。
- `临时状态` 作为被讨论的对象不会被误判为临时请求，但 `这次 / 本轮 / 暂时 / temporarily` 这类作用域提示仍会阻止长期写入。

检索与上下文黄金集当前是 400 条固定回归样本，由
`tests/fixtures/golden_cases/generate_retrieval_context.py` 生成并写入
`tests/fixtures/golden_cases/retrieval_context.jsonl`。

这组样本现在定位为本地检索/上下文机制回归集，而不是真实语义召回基准。它大量使用 `RET_*` / `CONTEXT_*` 人工标记，目的是稳定验证 scope 优先级、memory_type 过滤、inactive 排除、confirmed 排序、limit、token_budget 和 warning；真实自然语言 query 改写与 no-match 能力主要由 `semantic_retrieval_cn.jsonl`、`semantic_retrieval_v2.jsonl` 和 `semantic_retrieval_public.jsonl` 覆盖。

当前覆盖：

```text
当前 repo scope 优先：60
memory_type 过滤：50
global fallback：40
inactive 记忆排除：40
confirmed 优先于 likely：40
limit 截断：30
confirmed 记忆注入上下文：50
inactive 记忆不注入上下文：30
token_budget 截断：30
低置信/未验证 warning：30
```

生命周期黄金集当前是 300 条固定回归样本，由
`tests/fixtures/golden_cases/generate_lifecycle.py` 生成并写入
`tests/fixtures/golden_cases/lifecycle.jsonl`。

当前覆盖：

```text
标记 stale 后不再检索：75
archive 后不再检索：75
新候选 supersede 旧记忆：75
stale 后 archive 的版本链：75
```

自然语言任务召回黄金集当前是 300 条固定回归样本，由
`tests/fixtures/golden_cases/generate_task_recall.py` 生成并写入
`tests/fixtures/golden_cases/task_recall.jsonl`。

当前覆盖：

```text
写启动说明时召回文档偏好、启动命令和验证规则：60
排错任务召回 troubleshooting 和环境事实：50
测试验证任务召回 pytest、ruff 和历史排错经验：50
项目结构任务召回模块事实和文档流程：40
偏好任务召回用户长期偏好：40
inactive 记忆不被自然语言任务召回：40
其他 repo 记忆不串入当前 repo：20
```

自动巩固黄金集当前是 300 条固定回归样本，由
`tests/fixtures/golden_cases/generate_consolidation.py` 生成并写入
`tests/fixtures/golden_cases/consolidation.jsonl`。

当前覆盖：

```text
合并用户偏好：60
合并项目事实：60
跨 scope 不合并：45
不同 memory_type 不合并：45
inactive 记忆不参与巩固：45
低置信记忆不参与巩固：45
```

前五组黄金测试集合计 3300 条：写入门禁 2000 条、检索与上下文 400 条、生命周期 300 条、自然语言任务召回 300 条、自动巩固 300 条。

知识图谱召回黄金集当前是 300 条固定回归样本，由
`tests/fixtures/golden_cases/generate_graph_recall.py` 生成并写入
`tests/fixtures/golden_cases/graph_recall.jsonl`。

当前覆盖：

```text
repo 实体召回：60
file 实体召回：50
tool 实体召回：50
error -> solution 召回：50
跨 scope 图谱防串扰：40
旧记忆不被图谱召回：30
低置信关系不被强召回：20
```

前六组黄金测试集合计 3600 条。

图谱冲突黄金集当前是 300 条固定回归样本，由
`tests/fixtures/golden_cases/generate_graph_conflicts.py` 生成并写入
`tests/fixtures/golden_cases/graph_conflicts.jsonl`。

当前覆盖：

```text
启动命令冲突：80
数据库冲突：60
默认语言冲突：50
同目标重复关系不误报：40
跨 scope 冲突不串扰：30
inactive 来源不参与冲突：20
低置信关系不参与冲突：20
```

前七组黄金测试集合计 3900 条。

冲突解决黄金集当前是 300 条固定回归样本，由
`tests/fixtures/golden_cases/generate_conflict_reviews.py` 生成并写入
`tests/fixtures/golden_cases/conflict_reviews.jsonl`。

当前覆盖：

```text
接受新事实并 supersede 旧记忆：80
保留已有事实并 supersede 新记忆：50
全部归档：40
转人工确认：30
重复 pending review 不重复生成：30
同目标关系不生成 review：30
inactive 或低置信关系不生成 review：40
```

当前黄金测试集总量为 7020 条。新增的 `session_route.jsonl` 为 240 条短期记忆分流样本，覆盖 session/ignore/long_term/reject/ask_user，以及 6 类 session memory type；`session_route_splitting.jsonl` 为 24 条多信息分流样本，覆盖单句多原子项和多 event 批量输入；`task_boundary.jsonl` 为 46 条任务边界样本，覆盖 same_task 子步骤、显式切换、完成、取消、短确认和承接下一步；`session_closeout.jsonl` 为 160 条短期记忆收尾样本，覆盖 keep/discard/summarize/promote_candidate 和敏感过滤。`semantic_retrieval_cn.jsonl` 为 150 条中文语义召回样本，覆盖工程协作、记忆规则、隐私边界、日常偏好和 no-match。

当前还支持：

```text
list_candidates(status="pending")
edit_candidate(candidate_id, ...)
approve_candidate(candidate_id)
reject_candidate(candidate_id)
compose_context(task, memories, token_budget=...)
propose_consolidations(scope=..., memory_type=...)
commit_consolidation(candidate_id)
reject_consolidation(candidate_id)
upsert_entity(entity)
create_relation(relation)
graph_recall_for_task(task, store, scope=...)
detect_graph_conflicts(scope=..., relation_type=...)
create_conflict_reviews(scope=..., relation_type=...)
resolve_conflict_review(review_id, action=...)
list_retrieval_logs(source=..., memory_id=...)
add_retrieval_feedback(log_id, feedback=...)
get_memory_usage_stats(memory_id)
list_memory_usage_stats(recommended_action=...)
create_maintenance_reviews(scope=..., recommended_action=...)
resolve_maintenance_review(review_id, action=...)
RemoteLLMClient(...).route_memories([event, ...])
RemoteLLMClient(...).closeout_session_memories(session_id=..., session_memories=[...])
RemoteLLMClient(...).plan_recall(task="...")
RemoteLLMClient(...).extract_candidates(event)  # legacy long-term-only
RemoteEmbeddingClient(...).embed_texts([...])
orchestrate_recall(task, store, remote_llm=..., remote_embedding=..., session_store=...)
```

运行测试：

```bash
python -m pytest
```

冲突审查 CLI：

```bash
memoryctl --db data/memory.sqlite reviews generate --scope repo:C:/workspace/demo
memoryctl --db data/memory.sqlite reviews list --status pending
memoryctl --db data/memory.sqlite reviews show <review_id>
memoryctl --db data/memory.sqlite reviews resolve <review_id> --action accept_new --reason "verified from package.json"
```

维护建议审查 CLI：

```bash
memoryctl --db data/memory.sqlite maintenance generate --scope repo:C:/workspace/demo
memoryctl --db data/memory.sqlite maintenance list --status pending
memoryctl --db data/memory.sqlite maintenance show <review_id>
memoryctl --db data/memory.sqlite maintenance resolve <review_id> --action mark_stale --reason "usage review accepted"
```

远程适配器调试 CLI：

```bash
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
# DEEPSEEK_API_KEY / DASHSCOPE_API_KEY should already be configured in the environment.
memoryctl --db data/memory.sqlite remote status
memoryctl --db data/memory.sqlite remote health
memoryctl --db data/memory.sqlite remote route --event-id <event_id> --json
memoryctl --db data/memory.sqlite remote extract <event_id> --json
memoryctl --db data/memory.sqlite remote import <event_id> --json
memoryctl --db data/memory.sqlite remote evaluate --event-id <event_id> --json
memoryctl --db data/memory.sqlite remote embed "memory text" --json
memoryctl --db data/memory.sqlite remote embed-memory <memory_id> --json
memoryctl --db data/memory.sqlite remote embed-backfill --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote hybrid-search "部署前要检查什么" --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote guarded-hybrid-search "部署前要检查什么" --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote selective-llm-guarded-hybrid-search "当前服务的 SLA 数字是多少？" --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_v2.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_cn.jsonl --selective-llm-judge --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --embedding-cache data/eval_embedding_cache.jsonl --report-path data/retrieval_report.json --case-concurrency 4 --judge-group-size 4 --judge-concurrency 2 --json
python tools/benchmark_remote_retrieval.py --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --limit 60 --embedding-cache data/benchmark_remote_retrieval_embeddings.jsonl --output-dir data/remote_retrieval_benchmarks --case-concurrency 4
python tools/evaluate_session_route.py --fixture tests/fixtures/golden_cases/session_route.jsonl --sample-size 50 --sample-seed 20260430 --case-concurrency 4 --failure-limit 20 --report-path data/session_route_eval_50.json
python tools/evaluate_session_route_splitting.py --fixture tests/fixtures/golden_cases/session_route_splitting.jsonl --case-concurrency 4 --failure-limit 20 --report-path data/session_route_splitting_eval_24.json
python tools/evaluate_task_boundary.py --fixture tests/fixtures/golden_cases/task_boundary.jsonl --case-concurrency 4 --failure-limit 20 --report-path data/task_boundary_eval_46.json
python tools/evaluate_session_closeout.py --fixture tests/fixtures/golden_cases/session_closeout.jsonl --sample-per-category 1 --sample-seed 20260430 --case-concurrency 4 --failure-limit 20 --report-path data/session_closeout_eval_16.json
```

Route input policy: `events` are writable source events, while `recent_events` are read-only context. The LLM may use `recent_events` to resolve references, distinguish long-term versus session memory, and judge `task_boundary`, but every non-ignore route item must cite at least one current `events[].id` in `source_event_ids`. Items that only cite `recent_events` are filtered locally with `filtered_context_only_route_item`.

`remote route` 是当前推荐入口：一次远程调用把 event 分流为长期候选、短期会话记忆、忽略、拒绝或需要确认，并可在同一轮返回观察型 `task_boundary`。API 中的 session route 会进入运行期短期记忆库，后续 `/context/compose`、`/recall/task` 和 `/recall/orchestrated` 可按 `session_id` 优先注入；`task_boundary` 默认只返回和记录，不自动切换任务，真正的任务结束整理由 `/session/closeout` 显式触发。CLI 仍只在本次命令响应里返回短期项。`remote extract` 和 `remote import` 保留为 legacy long-term-only 调试入口，只适合单独观察长期候选提取链路。

`/recall/orchestrated` 是当前推荐的智能体召回入口。默认 `use_remote_planner=true`：如果远程 LLM 已配置，会先用 LLM planner 生成召回计划；如果远程不可用或返回不合法，会自动回退本地 planner。`use_remote=true` 时还会启用 remote embedding 和可选 LLM judge；未启用远程 embedding 时，即使 planner 建议混合召回，也会降级为本地 keyword，保证基础链路不依赖网络。

`/session/closeout` 会把当前 session memory 交给远程 LLM 做结算判断，逐条返回 `keep / discard / summarize / promote_candidate`。API 会按 LLM 决策把 `discard/summarize/promote_candidate` 的短期项标记为 `dismissed`；其中 `promote_candidate` 会先创建长期候选并继续走本地 policy gate，不会直接写入长期记忆。

`evaluate_session_closeout.py` 是 `/session/closeout` 的真实远程评估脚本，重点看任务完成、取消、切换或仍待确认时，短期记忆是否正确保留、丢弃、摘要或升级为长期候选。它按 alias 统计 action accuracy、strict accuracy、candidate type mismatch、forbidden promotion、unsafe promotion 和 missing decisions。2026-04-30 的 16-case 分层 smoke 结果为 case `16/16`、action item `32/32`、strict item `32/32`、unsafe promotion `0`，报告保存在 `data\session_closeout_eval_16.json`。

`evaluate_session_route.py` 是 `remote route` 的真实远程评估脚本，重点看短期记忆分流是否把当前任务状态、临时规则、工作事实、待决事项、情绪状态和草稿备注放进 `session`，同时把简单确认、敏感内容、长期偏好和阻塞确认分到正确 route。当前同 seed 50 条验收结果为 route `50/50`、strict `42/50`、serious failures `0`；strict mismatch 主要是短期细分类或长期 workflow/project_fact 的边界漂移。

`evaluate_session_route_splitting.py` 专门测试复合输入：单句里同时包含长期偏好、当前任务规则、确认请求，或多条 event 一起传入。当前 24 条验收结果为 route case `24/24`、route item `57/57`、strict item `51/57`、serious failures `0`，说明主分流已经覆盖“多信息差分”场景。

`evaluate_task_boundary.py` 专门测试 `task_boundary`：重点看“测试/验证/解释/举例/同步文档/修当前问题”是否保持 `same_task`，以及“接下来做 X / 换成 X / 完成 / 取消”是否给出正确边界。当前本地 boundary gate 已调整为 soft gate：只做结构规范化、明确完成/取消/切换兜底，以及弱证据 `switch_task/new_task` 降置信，不再靠本地子步骤关键词强制改判。2026-04-30 真实远程 46 条 soft gate 验收结果为 action `46/46`、strict `46/46`，报告保存在 `data\task_boundary_eval_soft_46_final.json`。

外部公开记忆数据集只作为参考语料，原始数据不进入仓库回归 fixture；当前已落地一组 public-inspired 合成召回 fixture。下载位置和使用方式见 `docs/12-public-memory-datasets.md`。

当前默认远程模型名写在 `remote.py` 中：

```text
LLM: deepseek-v4-flash
Embedding: tongyi-embedding-vision-flash-2026-03-06
```

DeepSeek 模式下，LLM 使用 OpenAI-compatible `/chat/completions`；vision embedding 仍保留原来的 `tongyi-embedding-vision-flash-2026-03-06` 默认模型，并优先走 DashScope multimodal embedding。`remote evaluate-retrieval --selective-llm-judge` 会分别使用 LLM config 与 embedding config，避免把 embedding 请求发到 DeepSeek。

大样本远程召回评估建议固定传 `--embedding-cache`、`--report-path` 和适度的 `--case-concurrency`。embedding cache 是 JSONL 追加文件，命令中断后用同一个 cache 重跑会复用已完成向量，相当于 embedding 层面的断点续跑；report path 会保存完整 JSON 结果，便于对比不同模型、阈值和 fixture 版本。`--case-concurrency` 默认是 1；真实远程建议先用 3 或 4，确认限流和稳定性后再提高。case 阶段只做本地召回和 guard，不直接调用 DeepSeek；需要远程复核的样本会先变成 pending judge task，再由 `--judge-concurrency` 控制同时几个 DeepSeek 请求，`--judge-group-size` 控制每个请求里放几条 task：`--judge-group-size 1 --judge-concurrency 4` 是并发单条 judge；`--judge-group-size 2|4 --judge-concurrency 2` 是少请求数的小批量 judge。

开发环境也可以直接用模块方式运行：

```bash
$env:PYTHONPATH = "src"
python -m memory_system.cli --db data/memory.sqlite reviews list --status pending
```

事件日志示例：

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

候选记忆和长期记忆示例：

```python
from memory_system import EventCreate, EventLog, MemoryStore, SearchMemoryInput

db_path = "data/memory.sqlite"
events = EventLog(db_path)
memories = MemoryStore(db_path)

event = events.record_event(
    EventCreate(
        event_type="user_message",
        content="以后技术文档默认用中文，并且区分事实和推断。",
        source="conversation",
        scope="global",
    )
)

candidate = memories.propose_memory(event)[0]
decision = memories.evaluate_candidate(candidate.id)
memory = memories.commit_memory(candidate.id, decision.id)

results = memories.search_memory(
    SearchMemoryInput(query="中文", memory_types=["user_preference"], scopes=["global"])
)
```

上下文组装示例：

```python
from memory_system import compose_context

block = compose_context("写项目说明", results, token_budget=1000)
print(block.content)
```

启动 API：

```bash
python -m uvicorn memory_system.api:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
```

核心接口：

```text
GET  /health
GET  /remote/status
GET  /remote/health
POST /remote/route
POST /remote/extract/{event_id}
POST /remote/embed
POST /remote/evaluate-candidates
POST /remote/evaluate-retrieval
POST /events
GET  /events/{event_id}
GET  /events
POST /candidates/from-event/{event_id}
POST /candidates/from-event/{event_id}/remote
GET  /candidates
PATCH /candidates/{candidate_id}
POST /candidates/{candidate_id}/evaluate
POST /candidates/{candidate_id}/approve
POST /candidates/{candidate_id}/reject
POST /memories/commit
POST /memories/search
POST /memories/search/remote-hybrid
POST /memories/search/remote-guarded-hybrid
POST /memories/embeddings/remote-backfill
POST /memories/{memory_id}/embedding/remote
GET  /retrieval/logs
GET  /retrieval/logs/{log_id}
POST /retrieval/logs/{log_id}/feedback
GET  /memories/usage
GET  /memories/{memory_id}/usage
POST /maintenance/reviews/from-usage
GET  /maintenance/reviews
GET  /maintenance/reviews/{review_id}
POST /maintenance/reviews/{review_id}/resolve
GET  /memories/{memory_id}
GET  /memories/{memory_id}/versions
POST /memories/{memory_id}/stale
POST /memories/{memory_id}/archive
POST /memories/{memory_id}/supersede
POST /graph/entities
GET  /graph/entities
GET  /graph/entities/{entity_id}
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
POST /context/compose
POST /recall/task
POST /recall/orchestrated
POST /recall/graph
POST /session/closeout
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
- [10-golden-case-examples.md](docs/10-golden-case-examples.md)：黄金测试集具体样例、synthetic 测试事实和期望行为说明
- [11-remote-adapters.md](docs/11-remote-adapters.md)：远程 LLM / embedding 适配器契约、配置和验证方式
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)：当前项目说明、实现范围、远程实测结果和常用命令
- [RULE_JUDGMENT.md](RULE_JUDGMENT.md)：写入门禁、召回、上下文注入、生命周期和远程治理的规则判断说明

## 6. 初始推荐路线

推荐从一个保守但结构清晰的 MVP 开始：

```text
Event Log
  -> Memory Router
  -> long_term / session / ignore / reject / ask_user
  -> Long-term Policy Gate
  -> Session Memory Store
  -> Orchestrated Recall
  -> Context Composer
```

第一阶段不要急于全自动写入，也不要过早引入复杂向量架构。更稳妥的顺序是：

1. 先记录事件日志。
2. 从事件中抽取候选记忆。
3. 对候选记忆做人工确认或严格规则判断。
4. 将确认后的记忆写入结构化存储。
5. 用全文检索和标签检索支撑初期使用。
6. 当记忆规模和语义检索需求变大后，再加入向量检索。
7. 加入自动巩固、冲突修订、遗忘机制和多智能体共享记忆。

当前代码已经超过最初 MVP：除了“自动巩固”最小闭环，还加入了 `route_memories` 短长期分流、session memory、任务边界、session closeout、远程 embedding 混合召回、LLM planner 优先的 `orchestrate_recall(...)` 和轻量知识图谱。

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
