# 05. 检索与上下文注入

## 1. 检索不是简单相似度搜索

普通 RAG 常见流程是：

```text
query -> embedding -> topK -> inject
```

但记忆系统更适合使用任务驱动检索：

```text
理解当前任务
  -> 判断需要哪类记忆
  -> 选择检索通道
  -> 多路召回
  -> 重排序
  -> 压缩
  -> 注入上下文
```

原因是不同任务需要不同记忆。

例如：

- 问用户偏好：优先检索 `user_preference`
- 问项目架构：优先检索 `project_fact`
- 修 bug：优先检索 `troubleshooting`、`environment_fact`、`tool_rule`
- 写代码：优先检索项目约定、接口规则、历史决策

## 2. Retrieval Planner

Retrieval Planner 的职责是把当前任务转换成检索计划。

### 2.1 输入

```json
{
  "user_query": "这个项目启动失败了，帮我排查",
  "workspace": "C:\\Users\\Administrator\\Desktop\\example",
  "current_files": ["package.json", "src/server.ts"],
  "task_context": {
    "mode": "debugging"
  }
}
```

### 2.2 输出

```json
{
  "task_type": "debugging",
  "memory_types": [
    "troubleshooting",
    "environment_fact",
    "project_fact",
    "tool_rule"
  ],
  "scopes": [
    "repo:C:\\Users\\Administrator\\Desktop\\example",
    "global"
  ],
  "retrieval_channels": [
    "keyword",
    "vector",
    "graph"
  ]
}
```

## 3. 混合检索

推荐使用四路召回。

### 3.1 Keyword / BM25

适合精确内容：

- 文件路径
- 函数名
- 命令
- 错误码
- 配置项
- 端口号

### 3.2 Vector Search

适合语义相似内容：

- 类似排错经验
- 相似用户偏好
- 相关文档片段
- 旧对话摘要

### 3.3 Graph Search

适合实体关系：

- 某项目使用了什么工具
- 某模块依赖什么服务
- 某问题由哪个方案解决
- 某规则属于哪个仓库

### 3.4 Recent Context

适合当前会话里的短期信息：

- 当前用户目标
- 刚刚运行的命令
- 尚未验证的假设
- 正在编辑的文件

Recent Context 不一定写入长期记忆，但在当前任务中很重要。

## 4. 重排序策略

召回后需要统一重排序。

建议评分：

```text
final_score =
  relevance_score
  + scope_score
  + confidence_score
  + recency_score
  + reuse_score
  - staleness_penalty
  - conflict_penalty
```

### 4.1 Scope Score

范围越贴近当前任务，分数越高。

推荐优先级：

```text
current task
current repo
current project
current workspace
current user
global
```

### 4.2 Confidence Score

置信度越高，越应该被使用。

```text
confirmed > likely > inferred > unknown
```

### 4.3 Staleness Penalty

长期未验证或明确可能过期的记忆应降权。

例如：

- 依赖版本
- API 文档
- 组织成员
- 当前端口
- 临时运行状态

## 5. Recall Orchestrator

当前代码新增 `src/memory_system/recall_orchestrator.py`，作为智能体调用记忆的推荐入口。它不是新的底层检索算法，而是把已有能力编排成一条可控链路：

```text
task
  -> memory-needed check
  -> RecallPlanner
  -> keyword / guarded_hybrid / selective_llm_guarded_hybrid
  -> optional graph recall
  -> Context Composer
  -> retrieval_logs(source=orchestrated_recall)
```

`strategy="auto"` 的选择规则：

- 没有远程客户端：使用本地 keyword recall。
- 有 remote embedding：使用 `guarded_hybrid`。
- 有 remote embedding + remote LLM：使用 `selective_llm_guarded_hybrid`。

Orchestrator 的价值在于统一记录 retrieved / used / skipped / warnings / steps。这样后续做反馈、降权、遗忘和 no-match 调参时，不需要从多个分散日志里拼事实。

## 6. 上下文组装

Context Composer 应该输出紧凑、可解释、任务相关的内容。

### 5.1 注入格式

推荐格式：

```text
Relevant memory:

1. [confirmed][project_fact][repo:example]
   后端入口是 src/server.ts。
   Source: file observation, 2026-04-27

2. [confirmed][troubleshooting][repo:example]
   问题：npm run dev 启动失败
   经验：如果端口被占用，应先检查已有 Node 进程
   解决方式：使用 netstat 查端口并关闭对应进程
```

### 5.2 注入原则

- 只注入和当前任务相关的最少记忆
- 优先注入高置信度记忆
- 标记可能过期内容
- 不注入敏感内容
- 不注入互相冲突且未解决的内容
- 对用户偏好类记忆保持简洁
- 对排错经验保留问题和解决方式

## 7. 使用记忆时的回答原则

智能体使用记忆时应该区分：

- 这是已验证事实
- 这是历史偏好
- 这是旧经验，可能需要重新验证
- 这是推断，不应直接当事实

例如：

```text
根据已记录并验证过的项目事实，这个仓库之前使用 run-local.ps1 启动本地模式。不过这类启动命令可能随项目变化，我会先检查当前 package.json 和脚本文件再执行。
```

这种回答比直接说“项目就是这样启动”更安全。

## 8. 检索失败处理

如果没有检索到相关记忆，不应该编造。

推荐行为：

```text
没有找到相关长期记忆。
我会根据当前文件和命令结果重新确认。
```

如果检索到的记忆过期：

```text
找到一条历史记忆，但它可能已经过期。
我会把它作为线索，而不是直接当成当前事实。
```

## 9. 记忆预算

上下文窗口有限，因此需要记忆预算。

建议预算：

| 任务类型 | 记忆预算 |
| --- | --- |
| 简单问答 | 1-3 条 |
| 项目查询 | 3-8 条 |
| 排错任务 | 5-12 条 |
| 大型重构 | 8-20 条 |
| 长期规划 | 10-30 条摘要 |

预算不足时优先保留：

1. 当前 repo / project 范围
2. confirmed 记忆
3. 最近验证过的记忆
4. 直接影响操作安全的规则
5. 用户明确偏好

## 10. 检索使用日志

检索优化不能只靠感觉，需要记录每次任务里“想起了什么”和“实际用了什么”。

当前实现会在这些路径写入 `retrieval_logs`：

```text
search_memory        -> source=search
POST /context/compose -> source=context
recall_for_task      -> source=task_recall
graph_recall_for_task -> source=graph_recall
orchestrate_recall   -> source=orchestrated_recall
```

每条日志至少记录：

```text
query / task / task_type / scope / source
retrieved_memory_ids
used_memory_ids
skipped_memory_ids
warnings
metadata
feedback / feedback_reason
```

这样后续可以做三件事：

- 排序优化：分析哪些记忆经常被召回但没有进入 context。
- 降权和遗忘：分析哪些记忆长期没有被使用，或反馈为 `not_useful`。
- 策略调试：对比 `task_recall`、`graph_recall` 和 `orchestrated_recall` 在不同任务类型下的实际命中情况。

当前维护建议保持保守：

```text
keep: 使用信号正常，或 useful 反馈更强。
review: 多次被召回但从未使用，需要人工复核是否太宽泛或已不相关。
mark_stale: active 记忆多次 not_useful，建议退出默认检索。
archive: stale 记忆仍然无用，建议只保留历史审计。
```

这些建议不会自动执行状态变更。真正的 `mark_stale` 和 `archive` 仍然要走显式生命周期操作。

当前已经有维护审查队列：

```text
usage stats -> maintenance review item -> resolve -> lifecycle change
```

也就是说，系统可以批量发现低质量记忆，但仍然需要显式 resolve 才会改变长期记忆状态。

## 11. 远程 Embedding 的位置

当前远程 embedding 只完成“调用和验证”：

```text
texts -> RemoteEmbeddingClient -> vectors
```

它还没有接入默认召回排序，也没有写入向量索引。这样可以先验证三件事：

- 远程服务是否稳定。
- 向量维度是否一致。
- 调用延迟是否能接受。

等远程 embedding 质量和速度稳定后，再把它接入混合检索：

```text
FTS5 keyword recall
+ scope / type / confidence filters
+ remote embedding vector recall
+ local rerank
+ context budget composer
```

远程向量只能影响候选召回和排序，不能直接决定是否注入上下文；最终仍然要经过 status、scope、confidence 和 token budget 过滤。

## 12. 当前 Hybrid Search 实现

当前已经加入第一版本地向量缓存和混合检索：

```text
memory_items
  -> remote embed-memory
  -> remote embed-backfill
  -> memory_embeddings(memory_id, model, vector_json)
  -> search_memory(retrieval_mode=semantic|hybrid, query_embedding=...)
```

默认 `search_memory` 仍然是 `keyword`，因此现有 FTS / LIKE 行为不会被远程服务影响。只有显式传入 `retrieval_mode="semantic"` 或 `retrieval_mode="hybrid"`，并提供 `query_embedding` 时，向量相似度才会参与排序。

API / CLI 入口：

```text
POST /memories/{memory_id}/embedding/remote
POST /memories/embeddings/remote-backfill
POST /memories/search/remote-hybrid
POST /memories/search/remote-guarded-hybrid
POST /memories/search/remote-llm-guarded-hybrid
POST /memories/search/remote-selective-llm-guarded-hybrid
POST /remote/evaluate-retrieval

memoryctl remote embed-memory <memory_id>
memoryctl remote embed-backfill --scope <scope>
memoryctl remote hybrid-search "<query>"
memoryctl remote guarded-hybrid-search "<query>"
memoryctl remote llm-guarded-hybrid-search "<query>"
memoryctl remote selective-llm-guarded-hybrid-search "<query>"
memoryctl remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval.jsonl
memoryctl remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_v2.jsonl
memoryctl remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_cn.jsonl --selective-llm-judge
memoryctl remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --embedding-cache data/eval_embedding_cache.jsonl --report-path data/retrieval_report.json --case-concurrency 4 --judge-group-size 4 --judge-concurrency 2
```

实现约束：

- 向量按 `(memory_id, model)` 缓存，同一条记忆可以有多个模型版本。
- `semantic` 模式只返回已有同维度向量的记忆。
- `hybrid` 模式会把关键词、scope、type、confidence 和 cosine similarity 合并排序。
- 远程 embedding 只在显式 API / CLI 调用时发生；普通写入和普通测试不依赖网络。

Batch / evaluation additions:

- `embed-backfill` only fills active memories missing the selected model embedding; it can be limited by scope and memory_type.
- `evaluate-retrieval` compares keyword / semantic / hybrid / guarded_hybrid against a fixture and reports false negatives, unexpected aliases, ambiguous candidates, and top-1 hits.
- `evaluate-retrieval` can also include `llm_guarded_hybrid` or `selective_llm_guarded_hybrid`, and reports per-category metrics for v1, v2, cn, and public-inspired fixtures.
- Large remote runs should pass `--embedding-cache`, `--report-path`, and a modest `--case-concurrency` value so repeated runs reuse completed vectors, keep a stable JSON report for diffing, and parallelize embedding prefetch plus case evaluation. Case workers only run local retrieval and guard; remote recall judge always runs afterward through a separate request concurrency and group-size layer. `--judge-group-size 1 --judge-concurrency 4` sends multiple one-task requests in parallel, while `--judge-group-size 2|4 --judge-concurrency 2` groups uncertain cases to reduce DeepSeek request count.
- `guarded-hybrid-search` adds a second-stage guard: low similarity is rejected; close top-1/top-2 scores first go through a lightweight local intent rerank, and only unresolved close matches are marked ambiguous.
