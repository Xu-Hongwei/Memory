# 11. 远程适配器

## 1. 目标

当前本地记忆框架已经覆盖事件日志、候选记忆、写入治理、长期记忆、召回、上下文组装、图谱冲突和维护审查。远程阶段的第一步不是把系统整体迁到云端，而是先加一层可替换的 Remote Adapter。

这一层的目标是：

- 让本地系统可以调用远程 LLM 做候选记忆提取。
- 让同一批 event 可以被远程 LLM 分流为长期记忆、短期会话记忆、忽略、拒绝或需要确认。
- 让本地系统可以调用远程 embedding 服务生成向量。
- 保持本地写入门禁、生命周期和审计逻辑不变。
- 先做 dry-run 对比，不让远程结果自动写入长期记忆。

## 2. 当前实现

代码入口：

```text
src/memory_system/remote.py
```

主要对象：

```python
RemoteAdapterConfig
RemoteHTTPClient
RemoteLLMClient
RemoteEmbeddingClient
RemoteMemoryRouteResult
RemoteCandidateImportResult
RemoteCandidateEvaluationResult
```

配置来自环境变量：

```text
MEMORY_REMOTE_BASE_URL          可选，远程服务地址
MEMORY_REMOTE_API_KEY           可选，Bearer token
MEMORY_REMOTE_TIMEOUT_SECONDS   可选，默认 30 秒
MEMORY_REMOTE_COMPATIBILITY     可选，generic / openai_compatible
MEMORY_REMOTE_EMBEDDING_COMPATIBILITY 可选，generic / openai_compatible / dashscope_multimodal
MEMORY_REMOTE_LLM_EXTRACT_PATH  可选，默认 /memory/extract
MEMORY_REMOTE_EMBEDDING_PATH    可选，默认 /embeddings
MEMORY_REMOTE_HEALTH_PATH       可选，默认 /health
```

Split configuration is now supported and preferred for mixed providers:

```text
LLM_REMOTE_BASE_URL
LLM_REMOTE_API_KEY
LLM_REMOTE_MODEL                 alias for LLM_REMOTE_LLM_MODEL
LLM_REMOTE_TIMEOUT_SECONDS

EMBEDDING_REMOTE_BASE_URL
EMBEDDING_REMOTE_API_KEY
EMBEDDING_REMOTE_MODEL           alias for EMBEDDING_REMOTE_EMBEDDING_MODEL
EMBEDDING_REMOTE_COMPATIBILITY   generic / openai_compatible / dashscope_multimodal
EMBEDDING_REMOTE_TIMEOUT_SECONDS
```

Resolution order:

- LLM clients use `LLM_REMOTE_*` first, then legacy `MEMORY_REMOTE_*`, then `DEEPSEEK_*`, then `DASHSCOPE_*`.
- Embedding clients use `EMBEDDING_REMOTE_*` first, then explicit legacy `MEMORY_REMOTE_*`, then `DASHSCOPE_*`, then the generic fallback.
- In the current mixed setup, LLM should resolve to DeepSeek, while embedding should resolve to DashScope multimodal embedding. This avoids sending `tongyi-embedding-vision-flash-2026-03-06` requests to the DeepSeek chat endpoint.

如果没有设置 `MEMORY_REMOTE_BASE_URL` 和 `MEMORY_REMOTE_API_KEY`，当前实现会自动尝试读取 DeepSeek 环境变量：

```text
DEEPSEEK_BASE_URL
DEEPSEEK_API_KEY
DEEPSEEK_MODEL
```

如果 DeepSeek 环境变量也不存在，才会继续尝试读取百炼 / DashScope 环境变量：

```text
DASHSCOPE_BASE_URL
DASHSCOPE_API_KEY
DASHSCOPE_MODEL
DASHSCOPE_EMBEDDING_MODEL
```

当前本地文件中固定的默认模型名：

```text
LLM: deepseek-v4-flash
Embedding: tongyi-embedding-vision-flash-2026-03-06
```

当检测到 `DEEPSEEK_*`、`DASHSCOPE_BASE_URL`、地址包含 `api.deepseek.com` 或地址包含 `/compatible-mode/v1` 时，LLM adapter 会进入 OpenAI-compatible 模式：

```text
LLM path: /chat/completions
Health path: /models
```

`tongyi-embedding-vision-flash-2026-03-06` 不走 OpenAI-compatible `/embeddings`，而是走 DashScope 原生 multimodal embedding endpoint：

```text
https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding
```

## 3. 远程 LLM 提取契约

本地请求：

```json
{
  "schema": "memory_system.remote_candidate_extraction.v1",
  "event": {
    "id": "evt_xxx",
    "event_type": "user_message",
    "content": "以后技术文档默认用中文。",
    "source": "conversation",
    "scope": "global",
    "metadata": {},
    "created_at": "2026-04-27T00:00:00+00:00",
    "sanitized": false
  },
  "instructions": "Return JSON with a candidates array..."
}
```

远程响应：

```json
{
  "provider": "remote-llm",
  "warnings": [],
  "metadata": {},
  "candidates": [
    {
      "content": "用户偏好技术文档默认使用中文。",
      "memory_type": "user_preference",
      "scope": "global",
      "subject": "技术文档语言偏好",
      "source_event_ids": ["evt_xxx"],
      "reason": "用户明确表达了未来可复用偏好。",
      "claim": "用户偏好技术文档默认使用中文。",
      "evidence_type": "direct_user_statement",
      "time_validity": "persistent",
      "reuse_cases": ["future_responses", "documentation"],
      "scores": {
        "long_term": 0.9,
        "evidence": 1.0,
        "reuse": 0.8,
        "risk": 0.1,
        "specificity": 0.7
      },
      "confidence": "confirmed",
      "risk": "low"
    }
  ]
}
```

如果远程响应中缺少 `scope`、`source_event_ids`、`reason` 或 `claim`，本地适配器会用 event 做保守默认补齐。但 `memory_type`、`content`、`subject` 仍应由远程明确返回。

## 3.1 远程候选治理

远程 LLM 的输出不会直接进入候选池。`RemoteLLMClient.extract_candidates` 当前会先经过一层本地治理：

- 敏感事件 preflight：如果 event 已被标记为 sanitized，或内容包含 `[REDACTED]`、`token`、`secret`、`api key`、`password`、`cookie`、`bearer`、`authorization` 等敏感线索，直接返回空候选，并记录 `filtered_sensitive_remote_event`，不会发起远程 HTTP 请求。
- 敏感候选过滤：如果远程返回的 candidate 内容或 claim 中包含敏感线索，丢弃该候选，并记录 `filtered_sensitive_remote_candidate`。
- 闲聊偏好过滤：类似“刚才喝了一杯咖啡”这种带有当天/本轮上下文的随口喜欢，不会被保留为 `user_preference`，除非用户明确说“记住”“以后”“默认”“偏好”等稳定线索。
- 用户明确拒写过滤：如果用户说 `do not treat this as a preference`、`不要当成偏好`、`不用记` 等，远程返回的 `user_preference` 会被丢弃。
- 低证据偏好降级：`可能我更喜欢...但还没想好`、`以后都这样`、`maybe I prefer...` 这类候选不会被当作高置信偏好写入，会降级为 `confidence=inferred`、`evidence=0.4`，后续门禁应给出 `ask_user`。
- 低证据 fallback：如果远程模型没有返回候选，但 event 明显包含低证据长期偏好线索，本地治理会生成一个低置信 `user_preference` 候选，交给门禁确认，而不是直接写入。
- 稳定偏好 fallback：如果远程模型漏提了带有 `always` / `going forward` / `默认` 等稳定线索且有明确对象的偏好，本地可以补一个高置信 `user_preference` 候选；但低证据线索优先级更高，会先降级为 `ask_user`。
- metadata 锚定：如果 event metadata 已经给出 `memory_type`、`subject`、`claim` 或 `evidence_type`，本地治理会用这些字段规范化远程候选，减少远程 subject/type 漂移导致的重复和冲突漏判。
- 类型归一化：`问题 / 经验 / 解决方式 / 验证通过` 优先归为 `troubleshooting`；已确认运行环境状态优先 `environment_fact`；项目固定流程优先 `workflow`；已验证文件/源码观察优先 `project_fact`；固定命令或工具使用规则优先 `tool_rule`。

这层治理只处理高置信边界，不替代后续写入门禁。即使远程候选被导入，也只会进入 `pending`，仍需本地 policy evaluate 和 commit。`extract_candidates` 和依赖它的 `remote extract/import` 当前保留为 legacy long-term-only 调试入口。

## 3.2 统一远程分流契约

当前推荐入口是 `RemoteLLMClient.route_memories(events, recent_events=...)`。它一次远程调用可以处理多条 event，并要求模型把每个原子信息分到以下路线：

```text
long_term   稳定、可复用、适合进入长期候选的记忆
session     只对当前任务或当前对话有用的短期记忆
ignore      寒暄、简单确认、低信息闲聊或无记忆价值内容
reject      敏感、危险或不应保存的内容
ask_user    当前必须先向用户确认才能继续的内容
```

请求结构：

```json
{
  "schema": "memory_system.remote_memory_route.v1",
  "events": ["... EventRead ..."],
  "recent_events": ["... context-only EventRead ..."],
  "routes": {
    "long_term": "Stable reusable memory for future conversations or tasks.",
    "session": "Useful only for the current conversation or task.",
    "ignore": "Low-information replies, greetings, thanks, simple confirmations, or chatter.",
    "reject": "Sensitive, unsafe, or private-secret content.",
    "ask_user": "Immediate user confirmation is required before proceeding."
  },
  "session_memory_types": [
    "task_state",
    "temporary_rule",
    "working_fact",
    "pending_decision",
    "emotional_state",
    "scratch_note"
  ]
}
```

返回结构是 `RemoteMemoryRouteResult.items[]`，每项包含 `route`、`content`、`reason`，并在需要时带上 `memory_type`、`session_memory_type`、`scope`、`subject`、`source_event_ids`、`claim`、`evidence_type`、`time_validity`、`reuse_cases`、`scores`、`confidence` 和 `risk`。

本地接收后继续分层处理：

- `long_term`：转为 `MemoryCandidateCreate`，只创建 pending candidate，再执行本地 `evaluate_candidate`，不会自动 commit。
- `session`：转为 `SessionMemoryItemCreate`，作为当前会话短期记忆返回；当前 CLI/API 响应里 `session_persisted=false`。
- `ignore/reject/ask_user`：只返回分流结果，不写入长期记忆。

敏感事件仍会在远程请求前被本地 preflight 拦截；远程返回中的异常字段会被规范化，例如把误放到 `memory_type` 的 `temporary_rule` 移到 `session_memory_type`。

## 4. 远程 Embedding 契约

本地请求：

```json
{
  "schema": "memory_system.remote_embedding.v1",
  "texts": ["memory text"],
  "model": "embedding-model",
  "metadata": {}
}
```

远程响应可以是本项目格式：

```json
{
  "provider": "remote-embedding",
  "model": "embedding-model",
  "vectors": [[0.1, 0.2, 0.3]]
}
```

也可以是 OpenAI-style `data[].embedding`：

```json
{
  "model": "embedding-model",
  "data": [
    {"embedding": [0.1, 0.2, 0.3]}
  ]
}
```

当前阶段已经可以显式把向量写入本地 `memory_embeddings` 缓存表，并用于 semantic / hybrid 搜索。默认写入长期记忆时不会自动调用远程 embedding，避免普通记忆写入依赖网络、额度和模型波动。

百炼 / DashScope multimodal embedding 请求会使用：

```json
{
  "model": "tongyi-embedding-vision-flash-2026-03-06",
  "input": {
    "contents": [
      {"text": "memory text"}
    ]
  }
}
```

## 5. API

```text
GET  /remote/status
GET  /remote/health
POST /remote/route
POST /remote/extract/{event_id}
POST /remote/embed
POST /remote/evaluate-candidates
POST /remote/evaluate-retrieval
POST /candidates/from-event/{event_id}/remote
POST /memories/embeddings/remote-backfill
POST /memories/search/remote-hybrid
POST /memories/search/remote-guarded-hybrid
```

`/remote/route` 是推荐的远程分流入口：请求体传入 `event_ids`、可选 `recent_event_ids` 和 `session_id`，响应会把长期候选、短期会话记忆、忽略项、拒绝项和待确认项分开返回。长期项只创建 pending candidate 并附带本地 policy decision；短期项当前只在响应中返回，不持久化。

`/remote/extract/{event_id}` 是 legacy dry-run：它只返回远程长期候选，不会写入 `memory_candidates`。如果要写入，后续应显式调用本地候选创建和写入门禁流程。

`/candidates/from-event/{event_id}/remote` 是 legacy long-term-only import：它会调用远程 LLM，并把通过 schema 校验的候选写入本地 `memory_candidates`，状态为 `pending`。它仍然不会写入长期记忆；后续必须继续调用 `POST /candidates/{candidate_id}/evaluate` 和 `POST /memories/commit`。

## 6. CLI

```bash
$env:DEEPSEEK_BASE_URL = "https://api.deepseek.com"
$env:DEEPSEEK_API_KEY = "<configured in environment>"
$env:DEEPSEEK_MODEL = "deepseek-v4-flash"
memoryctl --db data/memory.sqlite remote status
memoryctl --db data/memory.sqlite remote health
memoryctl --db data/memory.sqlite remote route --event-id <event_id> --json
memoryctl --db data/memory.sqlite remote extract <event_id> --json
memoryctl --db data/memory.sqlite remote import <event_id> --json
memoryctl --db data/memory.sqlite remote embed "memory text" --json
```

`remote status` 不会输出 API key，只会显示 `api_key_configured`。

`remote route` 是推荐 CLI 入口；`remote extract` 和 `remote import` 保留为 legacy long-term-only 调试入口。

远程候选质量评估：

```bash
memoryctl --db data/memory.sqlite remote evaluate --event-id <event_id> --json
memoryctl --db data/memory.sqlite remote evaluate --source conversation --limit 20 --json
memoryctl --db data/memory.sqlite remote embed-backfill --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote guarded-hybrid-search "部署前要检查什么" --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_v2.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_cn.jsonl --selective-llm-judge --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --embedding-cache data/eval_embedding_cache.jsonl --report-path data/retrieval_report.json --case-concurrency 4 --judge-group-size 4 --judge-concurrency 2 --json
python tools/benchmark_remote_retrieval.py --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --limit 60 --embedding-cache data/benchmark_remote_retrieval_embeddings.jsonl --output-dir data/remote_retrieval_benchmarks --case-concurrency 4
```

`remote evaluate` 会同时运行本地规则 preview 和远程 LLM 提取，并返回差异报告；它不会写入 `memory_candidates`。

`remote evaluate-retrieval` 是只读评估，但会调用远程 embedding。大样本或真实远程测试时建议使用：

- `--embedding-cache`: 保存 text + model 对应的向量结果。cache 是 JSONL 追加文件，命令中断后重跑同一个 fixture 会复用已经完成的向量，减少重复远程调用。
- `--report-path`: 把完整评估结果写成稳定 JSON 文件。报告包含 summary、category_summary、每条 item、warnings 和 metadata，适合做 v1/v2、模型切换或阈值调整后的 diff。
- `--case-concurrency`: 控制同时评估多少条 case。大于 1 且启用 embedding cache 时，会先并发预取 fixture 中的唯一 embedding 文本，再并发评估每个 case。case 阶段只做本地召回和 guard，不直接调用 DeepSeek；需要远程复核的结果会先进入 pending judge task。真实远程建议先用 3 或 4。
- `--judge-concurrency`: 控制最多多少个远程 judge 请求同时在路上。
- `--judge-group-size`: 控制每个远程 judge 请求包含多少条 pending judge task。`1` 等价于 single judge；`2` 或 `4` 是小批量 judge。有效在途 task 上限约等于 `judge_concurrency * judge_group_size`，更大的 group size 需要单独测速确认。

API 侧对应字段是 `embedding_cache_path`、`case_concurrency`、`judge_concurrency` 和 `judge_group_size`。CLI 的 `--report-path` 只是本地落盘输出，不改变 API 返回结构。

## 7. 验证方式

当前测试使用本地 fake HTTP server 模拟远程服务：

```bash
python -m pytest tests/test_remote_adapters.py
```

覆盖点：

- `RemoteLLMClient` 能发送 event 并解析候选记忆。
- `RemoteEmbeddingClient` 能解析项目格式和 OpenAI-style embedding 响应。
- API / CLI 能把单条长期记忆写入 `memory_embeddings` 向量缓存。
- API / CLI 能对 query 生成远程 embedding，并执行本地 hybrid search。
- API / CLI `remote route` 能把同一批 event 分流为长期候选、短期记忆、忽略和拒绝，并保持长期候选只进 pending。
- API 远程提取保持 dry-run，不自动写库。
- API 远程导入作为 legacy long-term-only 入口，只写 pending candidate，不自动 commit 长期记忆。
- API 远程评估只读，不创建候选记忆。
- CLI `remote status` 不泄露 API key。
- CLI `remote route` 能从事件日志读取多条 event 并调用远程分流。
- CLI `remote extract` 能从事件日志读取 event 并调用 legacy 长期候选提取。
- CLI `remote import` 能把 legacy 远程候选写入本地候选队列。
- CLI `remote evaluate` 能比较本地规则和远程候选，且不写库。

## 8. 当前统计和下一步

当前已经可以把远程候选写入本地 pending candidate，并且已经把 50 条只读小样本固化为 `tests/fixtures/golden_cases/remote_candidate_quality_50.jsonl`。样本覆盖用户偏好、一次性请求、临时状态、敏感内容、排错经验、环境事实、项目流程、项目事实和工具规则。

```text
同一批 event
  -> 远程 LLM route_memories
  -> long_term 进入 pending candidate + 本地 evaluate_candidate
  -> session 进入当前会话短期记忆
  -> ignore/reject/ask_user 不写长期库
```

固化测试与 FN fallback 后的真实远程复测结果：

```text
total: 50
tp: 39
tn: 11
fp: 0
type_mismatch: 0
fn: 0
extra_noise: 0
skipped_sensitive_remote_calls: 4
avg_latency_ms_non_skipped: 14457.9
```

运行方式：

```bash
python -m pytest tests/test_remote_candidate_quality.py
$env:MEMORY_RUN_REMOTE_QUALITY = "1"
python -m pytest tests/test_remote_candidate_quality.py::test_remote_candidate_quality_live_fixture -s
```

结论：当前远程模型在这组样本上更偏“少误写”，敏感内容不会发起远程请求，噪声、类型漂移和已知 FN 已被本地治理压住。下一步可以在这套 fixture 的结构上继续扩到几百条，但仍应保持 live 远程测试默认跳过，避免普通测试依赖网络、额度和模型波动。

后续工程方向：

- 批量补齐缺失的 `memory_embeddings`。
- 当记忆规模变大后，把当前 JSON 向量缓存迁移到 sqlite-vec / Qdrant / pgvector。
- 记录远程调用延迟、失败率和模型版本。

Current embedding retrieval additions:

- `remote embed-backfill` and `POST /memories/embeddings/remote-backfill` batch-fill missing `memory_embeddings` for active memories.
- `tests/fixtures/golden_cases/generate_semantic_retrieval.py` generates the 50-case `semantic_retrieval.jsonl` paraphrase fixture for checking whether semantic / hybrid retrieval reduces keyword false negatives.
- `tests/fixtures/golden_cases/generate_semantic_retrieval_v2.py` generates the 200-case `semantic_retrieval_v2.jsonl` fixture, including daily chat preference/habit cases and no-match cases.
- `tests/fixtures/golden_cases/generate_semantic_retrieval_public.py` generates the 300-case `semantic_retrieval_public.jsonl` fixture, inspired by LongMemEval, LoCoMo, and RealMemBench task shapes without copying public dataset rows.
- `remote guarded-hybrid-search` and `POST /memories/search/remote-guarded-hybrid` add a second-stage guard that rejects low-similarity results, uses lightweight local intent rerank for close scores, and marks unresolved close matches as ambiguous.
- `remote evaluate-retrieval` and `POST /remote/evaluate-retrieval` compare keyword / semantic / hybrid / guarded_hybrid, and can optionally include `llm_guarded_hybrid` or `selective_llm_guarded_hybrid`. Reports include false negatives, unexpected aliases, ambiguous candidates, top-1 hits, judge call counts, per-category summaries, per-item warnings, embedding-cache metadata, prefetch metadata, worker count, and judge concurrency metadata.
- `tools/benchmark_remote_retrieval.py` runs a fixed remote retrieval speed matrix, writes one JSON report per configuration plus `summary.json`, and includes failure-case samples for the target mode.
- Remaining scale-up work is moving the JSON vector cache to sqlite-vec / Qdrant / pgvector when memory volume grows.
