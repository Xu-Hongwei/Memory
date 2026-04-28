# 当前项目说明

## 1. 项目定位

本项目是一个面向智能体的长期记忆系统原型。它不是简单保存聊天记录，也不是把所有内容直接塞进向量库，而是围绕“什么值得记、凭什么可信、什么时候召回、什么时候修正或遗忘”建立一套可治理的记忆框架。

当前系统的核心目标是：

- 让智能体能从用户消息、工具结果、文件观察和测试结果中提取候选记忆。
- 用本地规则判断候选是否能进入长期记忆。
- 保存来源事件、版本链、置信度、适用范围和状态。
- 支持关键词检索、语义检索、混合检索、上下文组装和图谱召回。
- 对远程 LLM 与 embedding 只做受控接入，不让远程结果绕过本地治理。

一句话概括：

```text
这是一个“少记、可信、可追溯、可修正”的智能体记忆系统。
```

## 2. 技术栈

当前实现采用：

```text
Python
FastAPI
Pydantic
SQLite
SQLite FTS5
pytest
Remote LLM / Remote Embedding Adapter
```

SQLite 负责 MVP 阶段的结构化存储、全文检索、版本记录和审计。远程模型只作为增强能力接入，核心写入门禁、生命周期和审计逻辑仍在本地完成。

## 3. 当前实现范围

当前已实现 Phase 1 到 Phase 6-lite，并接入远程模型测试链路和 Recall Orchestrator。

主要模块：

```text
src/memory_system/
  schemas.py              Pydantic 数据结构
  event_log.py            事件日志和基础脱敏
  memory_store.py         候选记忆、写入门禁、长期记忆、版本链、检索
  context_composer.py     上下文组装和预算控制
  task_recall.py          自然语言任务召回
  recall_orchestrator.py  统一召回编排层
  graph_recall.py         轻量知识图谱召回和冲突检测
  remote.py               远程 LLM / embedding HTTP 适配器
  remote_evaluation.py    远程候选和远程召回评测
  api.py                  FastAPI 接口
  cli.py                  命令行入口
```

当前数据层包含：

```text
events
memory_candidates
policy_decisions
memory_items
memory_versions
memory_embeddings
memory_entities
memory_relations
consolidation_candidates
conflict_review_items
retrieval_logs
maintenance_review_items
```

## 4. 记忆生命周期

一条长期记忆通常经历以下流程：

```text
event
  -> candidate
  -> policy decision
  -> commit memory
  -> search / recall / context
  -> feedback / maintenance
  -> stale / archive / supersede
```

系统不会把远程模型返回的候选直接写入长期记忆。候选必须先进入 `pending`，再经过本地 policy 判断，只有 `write` 或人工批准后才能 commit。

记忆状态：

```text
active       当前可检索、可注入上下文
stale        已过期，不作为当前事实默认使用
archived     已归档，只保留历史
rejected     被拒绝
superseded   被新记忆替代
```

## 5. 记忆类型

当前支持的 `memory_type`：

```text
user_preference   用户长期偏好
project_fact      已验证项目事实
tool_rule         固定工具规则或命令规则
environment_fact  已确认环境状态
troubleshooting   已验证排错经验
decision          项目或设计决策
workflow          固定工作流程
reflection        反思或总结
```

自动写入优先支持高置信、低风险、可复用的类型，例如 `user_preference`、`project_fact`、`tool_rule`、`environment_fact`、`troubleshooting`、`workflow` 和 `decision`。

## 6. 检索能力

当前检索分为四层：

```text
keyword          SQLite FTS / LIKE 关键词召回
semantic         远程 embedding 向量召回
hybrid           关键词 + embedding 混合排序
guarded_hybrid   混合召回后再做低分和歧义保护
```

检索默认只返回 `active` 记忆，并会按以下信号排序：

- 关键词命中
- 语义相似度
- 当前 `scope`
- `memory_type`
- `confidence`
- 更新时间

上下文组装会继续过滤 inactive 记忆，并对低置信、缺少 `last_verified_at`、预算耗尽等情况输出 warning。

### 6.1 Recall Orchestrator

`orchestrate_recall(...)` 是当前推荐给智能体使用的召回入口。它把原本分散的 planner、keyword search、远程 embedding guard、远程 LLM judge、图谱召回、上下文组装和 retrieval log 串成一条稳定链路：

```text
task
  -> memory-needed check
  -> strategy selection
  -> keyword / guarded_hybrid / selective_llm_guarded_hybrid
  -> optional graph recall
  -> no-match / skipped tracking
  -> context composer
  -> retrieval_logs(source=orchestrated_recall)
```

默认策略是 `auto`：没有远程客户端时使用本地 keyword；传入 remote embedding 时使用 `guarded_hybrid`；同时传入 remote LLM 时使用 `selective_llm_guarded_hybrid`。这层的重点不是替代底层检索，而是统一判断“该不该想起、想起哪些、哪些跳过、为什么跳过、最终哪些进入上下文”。

## 7. 远程模型接入

当前远程配置来自环境变量。代码里固定默认模型名：

```text
LLM: qwen3.6-flash
Embedding: tongyi-embedding-vision-flash-2026-03-06
```

远程 LLM 用于候选记忆提取，也用于召回候选的二次判断。远程 embedding 用于向量生成和语义召回。二者都不能绕过本地规则。

2026-04-28 的真实远程测试结果：

```text
remote status: configured=true
remote health: /models 可访问，qwen3.6-flash 可用

semantic_retrieval_public.jsonl / 300 cases
keyword:        passed=168 failed=132 FN=93 unexpected=119 top1=167
semantic:       passed=247 failed=53  FN=13 unexpected=53  top1=247
hybrid:         passed=247 failed=53  FN=13 unexpected=53  top1=247
guarded_hybrid: passed=242 failed=58  FN=18 unexpected=18 ambiguous=80 top1=242
```

2026-04-28 新增的中文语义召回集 `semantic_retrieval_cn.jsonl` 共 150 条。真实远程 embedding 分段跑完后，`semantic/hybrid` 在中文正向召回上表现强，但 no-match 会多召回；`guarded_hybrid` 能压噪声但会产生 ambiguous。随后加入具体事实风险触发器后，`cn_no_match_work` 的 `selective_llm_guarded_hybrid` 从 7/10 提升到 10/10，unexpected 从 3 降到 0。

结论：

- 远程 embedding 明显降低漏召回。
- `guarded_hybrid` 明显降低误召回。
- 当前短板是 no-match / abstention 场景，也就是“没有相关记忆时应该返回空”的判断还需要继续优化。

## 8. 黄金测试集

当前固定黄金测试集总量为 4950 条，位于：

```text
tests/fixtures/golden_cases/
```

主要覆盖：

```text
write_policy.jsonl                  2000
retrieval_context.jsonl              400
lifecycle.jsonl                      300
task_recall.jsonl                    300
consolidation.jsonl                  300
graph_recall.jsonl                   300
graph_conflicts.jsonl                300
conflict_reviews.jsonl               300
remote_candidate_quality_50.jsonl     50
semantic_retrieval.jsonl              50
semantic_retrieval_v2.jsonl          200
semantic_retrieval_cn.jsonl          150
semantic_retrieval_public.jsonl      300
```

`semantic_retrieval_public.jsonl` 参考 LongMemEval、LoCoMo 和 RealMemBench 的任务形态生成，但不复制外部数据原文。

其中 `retrieval_context.jsonl` 是本地检索/上下文机制回归集，主要保证 scope、类型过滤、inactive 排除、排序、预算裁剪和 warning 不退化。它含有 `RET_*` / `CONTEXT_*` 人工标记，不应被当成真实语义召回基准。真实 query 改写、no-match 和远程 embedding/LLM 召回能力，应主要看 `semantic_retrieval_cn.jsonl`、`semantic_retrieval_v2.jsonl` 和 `semantic_retrieval_public.jsonl`。

## 9. 常用命令

运行全部测试：

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q
```

检查黄金集重复和模板化问题：

```powershell
python tests\fixtures\golden_cases\audit_golden_cases.py --strict
python tests\fixtures\golden_cases\audit_golden_cases.py --show-template-groups 5
```

查看远程配置：

```powershell
$env:PYTHONPATH = "src"
python -m memory_system.cli --db data\memory.sqlite remote status --json
python -m memory_system.cli --db data\memory.sqlite remote health --json
```

跑远程语义召回评测：

```powershell
$env:PYTHONPATH = "src"
python -m memory_system.cli --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_public.jsonl --json
python -m memory_system.cli --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_cn.jsonl --selective-llm-judge --json
```

启动 API：

```powershell
$env:PYTHONPATH = "src"
python -m uvicorn memory_system.api:create_app --factory --host 127.0.0.1 --port 8000
```

## 10. 下一步方向

短期最值得继续做：

- 优化 no-match / abstention 判断，降低不该召回时的误召回。
- 根据 `semantic_retrieval_public.jsonl` 的失败项调整 guard 阈值和拒答策略。
- 把远程评测摘要固化进脚本，避免每次人工阅读完整 JSON。
- 为维护建议增加更细的人工审查视图。

中期方向：

- 将 JSON 向量缓存迁移到 sqlite-vec、Qdrant 或 pgvector。
- 增加更强的实体抽取和图谱关系抽取。
- 增加 Web UI，用于查看候选、冲突、召回日志和维护建议。
- 把 Memory MCP / Agent runtime 接入为真实使用层。
