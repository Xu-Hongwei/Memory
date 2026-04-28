# 11. 远程适配器

## 1. 目标

当前本地记忆框架已经覆盖事件日志、候选记忆、写入治理、长期记忆、召回、上下文组装、图谱冲突和维护审查。远程阶段的第一步不是把系统整体迁到云端，而是先加一层可替换的 Remote Adapter。

这一层的目标是：

- 让本地系统可以调用远程 LLM 做候选记忆提取。
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

如果没有设置 `MEMORY_REMOTE_BASE_URL` 和 `MEMORY_REMOTE_API_KEY`，当前实现会自动尝试读取百炼 / DashScope 环境变量：

```text
DASHSCOPE_BASE_URL
DASHSCOPE_API_KEY
```

当前本地文件中固定的默认模型名：

```text
LLM: qwen3.6-flash
Embedding: tongyi-embedding-vision-flash-2026-03-06
```

当检测到 `DASHSCOPE_BASE_URL` 或地址包含 `/compatible-mode/v1` 时，LLM adapter 会进入 OpenAI-compatible 模式：

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
- 类型归一化：`问题 / 经验 / 解决方式 / 验证通过` 优先归为 `troubleshooting`；已确认运行环境状态优先 `environment_fact`；项目固定流程优先 `workflow`；已验证文件/源码观察优先 `project_fact`；固定命令或工具使用规则优先 `tool_rule`。

这层治理只处理高置信边界，不替代后续写入门禁。即使远程候选被导入，也只会进入 `pending`，仍需本地 policy evaluate 和 commit。

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
POST /remote/extract/{event_id}
POST /remote/embed
POST /remote/evaluate-candidates
POST /remote/evaluate-retrieval
POST /candidates/from-event/{event_id}/remote
POST /memories/embeddings/remote-backfill
POST /memories/search/remote-hybrid
POST /memories/search/remote-guarded-hybrid
```

`/remote/extract/{event_id}` 是 dry-run：它只返回远程候选，不会写入 `memory_candidates`。如果要写入，后续应显式调用本地候选创建和写入门禁流程。

`/candidates/from-event/{event_id}/remote` 会调用远程 LLM，并把通过 schema 校验的候选写入本地 `memory_candidates`，状态为 `pending`。它仍然不会写入长期记忆；后续必须继续调用 `POST /candidates/{candidate_id}/evaluate` 和 `POST /memories/commit`。

## 6. CLI

```bash
$env:DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:DASHSCOPE_API_KEY = "<configured in environment>"
memoryctl --db data/memory.sqlite remote status
memoryctl --db data/memory.sqlite remote health
memoryctl --db data/memory.sqlite remote extract <event_id> --json
memoryctl --db data/memory.sqlite remote import <event_id> --json
memoryctl --db data/memory.sqlite remote embed "memory text" --json
```

`remote status` 不会输出 API key，只会显示 `api_key_configured`。

远程候选质量评估：

```bash
memoryctl --db data/memory.sqlite remote evaluate --event-id <event_id> --json
memoryctl --db data/memory.sqlite remote evaluate --source conversation --limit 20 --json
memoryctl --db data/memory.sqlite remote embed-backfill --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote guarded-hybrid-search "部署前要检查什么" --scope repo:C:/workspace/demo --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_v2.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --json
```

`remote evaluate` 会同时运行本地规则 preview 和远程 LLM 提取，并返回差异报告；它不会写入 `memory_candidates`。

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
- API 远程提取保持 dry-run，不自动写库。
- API 远程导入只写 pending candidate，不自动 commit 长期记忆。
- API 远程评估只读，不创建候选记忆。
- CLI `remote status` 不泄露 API key。
- CLI `remote extract` 能从事件日志读取 event 并调用远程。
- CLI `remote import` 能把远程候选写入本地候选队列。
- CLI `remote evaluate` 能比较本地规则和远程候选，且不写库。

## 8. 当前统计和下一步

当前已经可以把远程候选写入本地 pending candidate，并且已经把 50 条只读小样本固化为 `tests/fixtures/golden_cases/remote_candidate_quality_50.jsonl`。样本覆盖用户偏好、一次性请求、临时状态、敏感内容、排错经验、环境事实、项目流程、项目事实和工具规则。

```text
同一批 event
  -> 本地规则 propose_memory
  -> 远程 LLM extract_candidates
  -> 对比 memory_type / confidence / evidence_type / scores / 是否应写入
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
- `remote evaluate-retrieval` and `POST /remote/evaluate-retrieval` compare keyword / semantic / hybrid / guarded_hybrid and report false negatives, unexpected aliases, ambiguous candidates, top-1 hits, and per-category summaries.
- Remaining scale-up work is moving the JSON vector cache to sqlite-vec / Qdrant / pgvector when memory volume grows.
