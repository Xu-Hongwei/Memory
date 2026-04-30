# 09. 验证与测试方案

## 1. 测试目标

记忆系统的测试目标不是证明它“记得多”，而是证明它：

- 不乱记
- 能追溯
- 能检索到该用的记忆
- 不会误用过期或冲突记忆
- 能拒绝敏感信息和一次性请求
- 在长期运行后仍然可维护

因此，测试要覆盖三层：

```text
代码正确性
  -> 记忆质量
  -> 真实任务效果
```

## 2. 测试分层

## 2.1 单元测试

验证单个函数或模块是否符合规则。

重点模块：

- `record_event`
- `propose_memory`
- `evaluate_candidate`
- `commit_memory`
- `search_memory`
- `compose_context`
- `consolidate`

典型测试：

```text
输入一次性请求 -> 不生成长期记忆
输入明确偏好 -> 生成 user_preference 候选
输入已验证项目事实 -> 允许写入 project_fact
输入未验证猜测 -> reject 或 pending
输入敏感信息 -> reject 或脱敏
输入冲突事实 -> update 或 ask_user
```

## 2.2 集成测试

验证完整链路是否工作。

核心链路：

```text
record_event
  -> propose_memory
  -> evaluate_candidate
  -> commit_memory
  -> search_memory
  -> compose_context
```

集成测试要证明：

- 每条长期记忆都能追溯到 source_event_ids
- `reject` 的候选不会进入 `memory_items`
- `commit_memory` 会写入 `memory_versions`
- FTS 索引能检索到新写入的记忆
- 上下文组装不会注入 archived / rejected 记忆

## 2.3 策略测试

验证写入门禁是否可靠。

策略测试比普通单元测试更重要，因为记忆系统最怕污染。

建议维护一组固定 case：

| 场景 | 期望 |
| --- | --- |
| 一次性改写请求 | reject |
| 临时任务状态 | reject |
| 用户明确长期偏好 | write 或 ask_user |
| 工具验证过的项目事实 | write |
| 用户猜测性表达 | reject 或 pending |
| 密钥、token、cookie | reject |
| 新事实替代旧事实 | update |
| 同内容重复写入 | merge 或 ignore |
| 已解决排错经验 | write |
| 未解决失败尝试 | reject |

## 2.4 检索测试

验证系统能在正确场景想起正确记忆。

测试维度：

- keyword 命中
- scope 优先级
- memory_type 过滤
- confidence 排序
- recency 降权
- stale / archived 排除

示例：

```text
给定：
- global 用户偏好：默认中文
- repo A 启动命令：npm run dev
- repo B 启动命令：pnpm dev

当 query 位于 repo A：
应优先返回 repo A 的 npm run dev，而不是 repo B 的 pnpm dev。
```

## 2.5 上下文注入测试

验证检索结果被正确压缩和注入。

测试点：

- 不超过 token_budget
- 高置信记忆优先
- 当前 repo 记忆优先
- 过期记忆带 warning
- 冲突未解决记忆不注入
- 敏感内容不注入
- 输出包含 memory_ids，方便审计

## 2.6 巩固测试

验证长期运行后的记忆不会越来越脏。

测试点：

- 重复记忆能合并
- superseded 记忆不再作为当前事实
- 长期未使用记忆可降权
- 反思型记忆必须保留来源
- 反思结果不能覆盖 confirmed 事实

## 3. 质量指标

## 3.1 写入质量

核心指标：

```text
write_precision = 正确写入数 / 总写入数
```

第一阶段优先追求高 precision。

建议目标：

```text
write_precision >= 0.95
```

也就是说，宁可少写，也不要乱写。

## 3.2 召回质量

核心指标：

```text
retrieval_recall = 应召回且被召回的记忆数 / 应召回的记忆数
```

早期目标可以低一点：

```text
retrieval_recall >= 0.80
```

召回不足可以通过搜索策略改进，但错误写入更难修复。

## 3.3 注入质量

核心指标：

```text
context_precision = 注入后实际有用的记忆数 / 注入记忆总数
```

建议目标：

```text
context_precision >= 0.90
```

## 3.4 安全质量

必须接近 100%。

```text
sensitive_rejection_rate >= 0.99
archived_memory_injection_rate = 0
rejected_memory_commit_rate = 0
```

## 4. 黄金测试集

建议建立 `tests/fixtures/golden_cases/`，并把“样本生成逻辑”和“固定测试样本”都纳入版本管理。

```text
golden_cases/
  generate_write_policy.py
  write_policy.jsonl
  generate_write_policy_cn_realistic.py
  write_policy_cn_realistic.jsonl
  generate_write_policy_en_realistic.py
  write_policy_en_realistic.jsonl
  generate_session_route.py
  session_route.jsonl
  generate_session_route_splitting.py
  session_route_splitting.jsonl
  generate_task_boundary.py
  task_boundary.jsonl
  generate_session_closeout.py
  session_closeout.jsonl
  generate_retrieval_context.py
  retrieval_context.jsonl
  generate_semantic_retrieval_cn.py
  semantic_retrieval_cn.jsonl
  generate_lifecycle.py
  lifecycle.jsonl
  generate_task_recall.py
  task_recall.jsonl
  generate_consolidation.py
  consolidation.jsonl
  generate_graph_recall.py
  graph_recall.jsonl
  generate_graph_conflicts.py
  graph_conflicts.jsonl
  generate_conflict_reviews.py
  conflict_reviews.jsonl
  retrieval.jsonl
  conflict.jsonl
  sensitive.jsonl
  context_composition.jsonl
  troubleshooting.jsonl
```

每条 case 包含：

```json
{
  "name": "negative_ordinary_or_unverified_001",
  "category": "negative_ordinary_or_unverified",
  "event": {
    "event_type": "user_message",
    "content": "帮我把这句话改得更自然一点。",
    "source": "conversation",
    "scope": "global"
  },
  "expected": {
    "candidates": []
  }
}
```

黄金测试集不应该直接复制网络语料，也不应该每次测试时动态调用模型生成。更稳妥的做法是：先参考主流框架的公开设计原则，人工改写成贴近日常交流的合成样本，再把生成器和生成结果固定下来。这样既能扩大覆盖面，又不会让测试结果随模型或网络状态漂移。

当前写入门禁固定样本分为三组：`write_policy.jsonl` 固定为 2000 条基础覆盖样本，`write_policy_cn_realistic.jsonl` 固定为 800 条中文真实表达补充样本，`write_policy_en_realistic.jsonl` 固定为 800 条英文真实表达补充样本。覆盖范围参考了主流框架的记忆分层共识，也参考公开记忆/对话数据集的场景结构：

- 短期和长期分开，临时状态不进入长期记忆。
- 用户、项目、组织等 scope 应该影响写入和检索。
- 语义事实、过往经验、流程规则要分类型保存。
- PII、token、密钥等敏感信息不能进入可检索长期记忆。
- 重复内容应合并，冲突事实应进入人工确认。

这些原则分别对应 LangGraph / Deep Agents 的 memory dimension、Mem0 的 conversation/session/user/org 分层、Letta 的 core/archival memory、Zep / Graphiti 的时间变化事实，以及 CrewAI 的 scope、importance、recency、semantic 综合信号。

`write_policy_cn_realistic.jsonl` 的重点不是扩大模板行数，而是约束真实中文表达边界：低证据偏好进入 `ask_user`，泛化不足的“以后都这样”需要确认，日常喜欢和情绪闲聊默认不写入，敏感内容不提候选，已验证排错、固定流程和环境事实应稳定写成对应类型。每条 case 都带 `scenario`、`utterance_style` 和 `source_family`，用于检查场景、表达方式和来源结构是否足够分散；当前补充集覆盖 213 个场景标签、28 种表达风格和 6 个来源族，输入文本模板化重复应保持为 0。

`write_policy_en_realistic.jsonl` 用同样结构约束英文表达边界：`going forward` / `by default` / `please follow this rule` 应写成长期偏好，`maybe I prefer` / `I might want` / `not sure whether` 应进入 `ask_user`，`do not treat this as a preference` / `for this run` / `today only` 默认不写入，`Problem / Lesson / Solution / Verified` 应稳定写成排错经验。当前补充集覆盖 193 个场景标签、28 种表达风格和 6 个来源族。

`session_route.jsonl` 固定为 240 条，专门验证短期记忆分流：`session` 覆盖 `task_state`、`temporary_rule`、`working_fact`、`pending_decision`、`emotional_state`、`scratch_note` 六类，另外用 `ignore`、`long_term`、`reject` 和 `ask_user` 做对照，防止把简单确认、长期偏好、敏感内容和阻塞确认误放进 session。默认单测只验证 fixture 形状和当前本地 fallback 可识别的 80 条子集；真实远程准确率应另走 opt-in 评估。

`session_route_splitting.jsonl` 固定为 24 条，专门验证复合输入：单句多原子项和多 event 批量输入都要求同时拆出 `long_term` 和 `session`，部分 case 额外包含 `ask_user` 或 `reject`。它补足了单句单标签测试看不到的“长期/短期信息差分”问题。

`session_closeout.jsonl` 固定为 160 条，专门验证任务完成、取消、切换或仍待确认时，已有短期记忆如何退出运行期：临时规则和取消任务应 `discard`，任务状态可 `summarize`，仍待用户确认的决策应 `keep`，已验证且可复用的工作事实/流程才允许 `promote_candidate`。敏感样本只使用 `[REDACTED]` 占位，远程 preflight 过滤后允许表现为 `missing`，但禁止升级为长期候选。

基础集分类数量：

```text
positive_user_preference: 300
negative_casual_like: 140
negative_temporary_state: 170
positive_project_fact: 180
positive_tool_rule: 140
positive_troubleshooting: 150
negative_sensitive: 120
review_low_evidence: 120
merge_duplicate: 110
ask_conflict: 110
negative_ordinary_or_unverified: 160
negative_question_only: 80
negative_emotional_or_social: 80
positive_workflow_explicit: 70
positive_environment_fact_explicit: 70
```

中文真实表达补充集分类数量：

```text
cn_positive_preference_direct: 60
cn_review_preference_uncertain: 45
cn_review_preference_underspecified: 35
cn_negative_temporary_request: 45
cn_negative_casual_like: 35
cn_negative_question_only: 30
cn_negative_emotional_or_social: 25
cn_positive_project_fact_observed: 45
cn_positive_troubleshooting_verified: 40
cn_positive_tool_rule_explicit: 25
cn_positive_workflow_explicit: 25
cn_positive_environment_fact_explicit: 20
cn_negative_sensitive: 25
cn_merge_duplicate: 15
cn_ask_conflict: 15
```

英文真实表达补充集分类数量：

```text
en_positive_preference_direct: 100
en_review_preference_uncertain: 70
en_review_preference_underspecified: 60
en_negative_temporary_request: 70
en_negative_casual_like: 70
en_negative_question_only: 60
en_negative_emotional_or_social: 50
en_positive_project_fact_observed: 80
en_positive_troubleshooting_verified: 60
en_positive_tool_rule_explicit: 40
en_positive_workflow_explicit: 40
en_positive_environment_fact_explicit: 30
en_negative_sensitive: 40
en_merge_duplicate: 15
en_ask_conflict: 15
```

这批样本已经实际发现过边界问题：`临时状态` 作为一个被讨论的概念，不应导致整条长期偏好被拒绝；英文的 `temporarily remember...` / `for this run...` 应该被识别为临时请求；`do not store casual likes as a stable preference` 在长期规则中应保留为偏好候选，而 `do not treat this as a preference` 应拒写。类似问题应继续通过黄金集驱动策略调整。

当前 `retrieval_context.jsonl` 固定为 400 条，用于测试本地检索/上下文 plumbing：scope、类型过滤、inactive 过滤、排序、limit、token_budget 和 warning。它和写入黄金集分开维护，避免把写入门禁问题和检索排序问题混在一起。

这组样本不是高质量真实语义召回基准。它大量使用 `RET_*` / `CONTEXT_*` 人工标记来保证精确命中和稳定断言，因此适合防止底层机制退化，不适合证明系统理解自然语言改写。真实 query 改写、hard negative、no-match 和远程模型判断，应由 semantic retrieval 系列 fixture 覆盖。

当前分类数量：

```text
retrieval_current_scope_priority: 60
retrieval_type_filter: 50
retrieval_global_fallback: 40
retrieval_excludes_inactive: 40
retrieval_confidence_ranking: 40
retrieval_limit: 30
context_includes_confirmed: 50
context_skips_inactive: 30
context_budget: 30
context_low_confidence_warnings: 30
```

这组样本重点检查：

- 当前 repo scope 是否优先于 global。
- memory_type 过滤是否生效。
- 当前 repo 没有命中时，是否能回退到 global 记忆。
- archived / stale / rejected 等 inactive 记忆是否不会被检索或注入。
- confirmed 是否优先于 likely。
- limit 和 token_budget 是否能稳定截断。
- 低置信或缺少验证时间的记忆是否带 warning。

当前 `lifecycle.jsonl` 固定为 300 条，用于测试“旧记忆如何退出当前事实集合”。它覆盖 stale、archive、supersede 三类状态变化，并要求每次变化都有 `memory_versions` 审计记录。

当前分类数量：

```text
mark_stale_excludes_retrieval: 75
archive_excludes_retrieval: 75
supersede_replaces_active: 75
stale_then_archive_versions: 75
```

这组样本重点检查：

- `active -> stale` 后不再被默认检索。
- `active/stale -> archived` 后保留历史但不进入召回。
- 新候选替代旧记忆时，旧记忆变为 `superseded`，新记忆保持 `active`。
- `create -> stale -> archive` 这种版本链可以完整追踪。

当前 `task_recall.jsonl` 固定为 300 条，用于测试“用户说一句自然语言任务时，系统应该主动想起哪些记忆”。它位于检索和上下文组装之上，测试的是 `task -> plan -> search -> context` 这条链路。

当前分类数量：

```text
startup_docs_recall: 60
debug_recall: 50
verification_recall: 50
project_structure_recall: 40
preference_recall: 40
inactive_exclusion_recall: 40
cross_scope_exclusion_recall: 20
```

这组样本重点检查：

- 写启动说明时，是否能想起文档偏好、启动命令和验证规则。
- 排错任务是否能想起 troubleshooting 和 environment_fact。
- 测试验证任务是否能想起 pytest、ruff 和历史测试排错经验。
- 项目结构任务是否能想起模块事实和相关文档流程。
- 用户要求按偏好回复时，是否能想起 global user_preference。
- stale / archived 记忆是否不会被自然语言任务召回。
- 其他 repo 的相似记忆是否不会串入当前 repo。

当前 `consolidation.jsonl` 固定为 300 条，用于测试“多条长期记忆什么时候应该被合并成一条更稳定的长期记忆”。它测试的是 `active memories -> consolidation candidate -> commit -> supersede sources` 这条链路。

当前分类数量：

```text
merge_user_preference: 60
merge_project_fact: 60
skip_cross_scope: 45
skip_different_type: 45
skip_inactive: 45
skip_low_confidence: 45
```

这组样本重点检查：

- 只有同 `scope + memory_type + subject` 的 active 记忆才会进入同一个巩固候选。
- `confirmed/likely` 可以参与巩固，`inferred/unknown` 不参与自动巩固。
- stale / archived / superseded 等 inactive 记忆不参与巩固。
- commit 巩固候选后，新 consolidated 记忆保持 `active`。
- 来源记忆会变为 `superseded`，并保留 `create -> supersede` 版本链。
- 默认检索只返回新的 consolidated 记忆，不再返回来源记忆。

当前 `graph_recall.jsonl` 固定为 300 条，用于测试“任务里的实体能否沿知识图谱关系召回相关长期记忆”。它测试的是 `task/scope -> seed entities -> relations -> source memories -> context` 这条链路。

当前分类数量：

```text
repo_entity_recall: 60
file_entity_recall: 50
tool_entity_recall: 50
error_solution_recall: 50
cross_scope_exclusion: 40
old_memory_exclusion: 30
low_confidence_relation_exclusion: 20
```

这组样本重点检查：

- 当前 repo 实体可以通过 scope 成为 seed entity。
- 任务里提到文件、工具或错误时，可以匹配到对应实体。
- 图谱可以沿两跳关系找到 source memory。
- 其他 repo 的实体关系不会串入当前 repo。
- stale / archived / superseded 记忆不会被图谱召回。
- `inferred/unknown` 关系不会直接注入上下文。

当前 `graph_conflicts.jsonl` 固定为 300 条，用于测试“图谱关系能否帮助系统发现同一属性的当前事实冲突”。它测试的是 `relations -> same from entity + relation type -> multiple active targets -> conflict` 这条链路。

当前分类数量：

```text
start_command_conflict: 80
database_conflict: 60
language_conflict: 50
same_target_no_conflict: 40
cross_scope_exclusion: 30
inactive_source_exclusion: 20
low_confidence_relation_exclusion: 20
```

这组样本重点检查：

- 同一个 repo 的 `has_start_command` 指向多个不同命令时会报冲突。
- 同一个 repo 的 `uses_database` 或 `default_language` 指向多个不同目标时会报冲突。
- 多条关系指向同一个目标时不会误报。
- 其他 repo 的冲突不会串入当前 repo。
- stale / archived / superseded 来源记忆不会参与当前冲突。
- `inferred/unknown` 关系不会参与当前冲突。

当前 `conflict_reviews.jsonl` 固定为 300 条，用于测试“检测到图谱冲突后，系统能否生成 review item，并按明确动作解决冲突”。它测试的是 `conflict -> review item -> resolve action -> lifecycle update` 这条链路。

当前分类数量：

```text
accept_new_resolution: 80
keep_existing_resolution: 50
archive_all_resolution: 40
ask_user_resolution: 30
duplicate_pending_review: 30
same_target_no_review: 30
inactive_or_low_confidence_no_review: 40
```

这组样本重点检查：

- `accept_new` 会保留推荐的新记忆，并把旧记忆标记为 `superseded`。
- `keep_existing` 会保留 review 中第一条当前事实，并把其他事实标记为 `superseded`。
- `archive_all` 会把冲突中的当前记忆全部归档。
- `ask_user` 会把 review 标记为 `needs_user`，不改变记忆状态。
- 相同冲突已有 pending review 时不会重复生成。
- 同目标关系、inactive 来源、低置信关系不会生成 review。

当前全部黄金测试集总计 7020 条。

CLI 审查入口不单独扩展黄金集，而是用 `tests/test_cli.py` 覆盖最小闭环：

```text
graph conflict -> reviews generate -> reviews list -> reviews show -> reviews resolve
```

这组测试重点确认命令行层没有绕开底层生命周期规则：`resolve --action accept_new` 后，旧记忆仍然必须进入 `superseded`，被保留的记忆仍然保持 `active`。同时保留 `--json` 输出测试，方便未来把同一套审查能力接到 Web UI。

检索使用日志目前用单元和 API 测试覆盖，不单独扩展黄金集：

```text
search_memory -> retrieval_logs(source=search)
POST /context/compose -> retrieval_logs(source=context)
recall_for_task -> retrieval_logs(source=task_recall)
graph_recall_for_task -> retrieval_logs(source=graph_recall)
orchestrate_recall -> retrieval_logs(source=orchestrated_recall)
POST /retrieval/logs/{log_id}/feedback -> 写入 useful / not_useful / mixed / unknown
```

这组测试确认两件事：一是日志不会改变原本召回结果；二是 retrieved / used / skipped 能区分“想起了什么”和“最终注入了什么”。新增的 orchestrated recall 测试还会确认低记忆需求消息可以跳过召回，以及远程 LLM judge 可以把具体事实 no-match 噪声挡在上下文外。

使用统计和维护建议也由单元/API 测试覆盖：

```text
GET /memories/{memory_id}/usage -> 返回 retrieved / used / skipped / feedback 计数
GET /memories/usage?recommended_action=mark_stale -> 返回维护建议队列
多次 retrieved 但 used=0 -> review
多次 not_useful -> mark_stale
```

这一步的测试重点是“建议可解释，但不自动改状态”。真正把记忆标记为 stale 或 archived，仍然由显式生命周期接口完成。

维护建议审查队列进一步覆盖：

```text
create_maintenance_reviews -> pending review
重复生成 -> 不重复创建 pending/needs_user review
resolve(action=review) -> needs_user，不改记忆
resolve(action=mark_stale) -> active 记忆变 stale，并写入版本链
resolve(action=archive) -> stale/active 记忆归档
memoryctl maintenance generate/show/resolve -> CLI 闭环
```

## 5. 最小 pytest 示例

### 5.1 写入门禁测试

```python
def test_reject_one_off_request(memory_app):
    event = memory_app.record_event(
        event_type="user_message",
        content="帮我把这句话改得更正式一点。",
        source="test",
        scope="global",
    )

    candidates = memory_app.propose_memory(event.id)

    assert candidates == []
```

### 5.2 已验证事实写入测试

```python
def test_commit_verified_project_fact(memory_app):
    event = memory_app.record_event(
        event_type="file_observation",
        content="package.json 中 dev 脚本已确认是 vite --host 0.0.0.0。",
        source="package.json",
        scope="repo:C:/workspace/demo",
    )

    candidate = memory_app.propose_memory(event.id)[0]
    decision = memory_app.evaluate_candidate(candidate.id)

    assert decision.decision == "write"

    memory = memory_app.commit_memory(candidate.id, decision.id)

    assert memory.memory_type == "project_fact"
    assert memory.source_event_ids == [event.id]
```

### 5.3 检索 scope 优先测试

```python
def test_search_prefers_current_repo(memory_app):
    memory_app.add_memory(
        content="项目启动命令是 npm run dev。",
        memory_type="project_fact",
        scope="repo:C:/workspace/a",
        subject="启动命令",
        confidence="confirmed",
    )
    memory_app.add_memory(
        content="项目启动命令是 pnpm dev。",
        memory_type="project_fact",
        scope="repo:C:/workspace/b",
        subject="启动命令",
        confidence="confirmed",
    )

    results = memory_app.search_memory(
        query="启动命令是什么？",
        scopes=["repo:C:/workspace/a", "global"],
        memory_types=["project_fact"],
    )

    assert results[0].content == "项目启动命令是 npm run dev。"
```

## 6. 端到端场景测试

端到端测试用于模拟真实智能体使用记忆。

## 6.1 用户偏好场景

流程：

```text
用户明确说：以后技术文档默认中文。
系统生成候选记忆。
写入门禁允许写入。
下一次用户要求写文档。
系统检索并注入“默认中文”。
最终输出中文文档。
```

验证：

- 偏好被正确写入
- 偏好 scope 正确
- 偏好被检索
- 偏好没有覆盖项目事实

## 6.2 项目事实场景

流程：

```text
工具读取 package.json。
确认启动命令。
写入 project_fact。
用户下次问如何启动。
系统先检索记忆，再重新验证高风险事实。
```

验证：

- 项目事实有文件证据
- 易变事实会带 `last_verified_at`
- 如果当前文件变化，旧事实会标记 stale

## 6.3 排错经验场景

流程：

```text
问题真实发生。
定位到原因。
解决方式验证通过。
写入 troubleshooting。
下次类似错误发生。
系统召回历史排错经验作为线索。
```

验证：

- 未解决失败尝试不写入
- 已验证解决方式写入
- 召回时标记适用范围
- 回答中不把旧经验当作当前事实

## 7. 人工评审

自动测试无法完全判断记忆质量，必须保留人工评审入口。

建议评审字段：

```text
是否长期有用
是否明确真实
是否非敏感
scope 是否正确
memory_type 是否正确
是否重复
是否冲突
是否需要过期时间
```

评审结论：

```text
approve
reject
edit
merge
mark_stale
delete
```

## 8. 回归测试

每次修改写入门禁、检索排序、巩固逻辑，都必须跑回归测试。

最低回归集：

```text
pytest tests/test_write_policy.py
pytest tests/test_memory_store.py
pytest tests/test_retrieval.py
pytest tests/test_context_composer.py
```

如果加入 API：

```text
pytest tests/test_api.py
```

如果加入向量检索：

```text
pytest tests/test_vector_retrieval.py
```

如果加入图谱：

```text
pytest tests/test_temporal_graph.py
```

## 9. 上线前验收

第一版上线前必须满足：

- 一次性请求不会写入长期记忆
- 未验证猜测不会写入 confirmed 记忆
- 敏感信息不会写入长期记忆
- 每条长期记忆都有来源事件
- 每次写入都有版本记录
- 检索能按 scope 优先排序
- archived / rejected 记忆不会注入上下文
- 排错经验符合“问题 / 经验 / 解决方式”结构
- 所有核心策略有 pytest 覆盖

## 10. Remote Adapter 测试

远程阶段的测试重点不是证明某个真实模型一定正确，而是证明本地系统对远程能力的边界控制是正确的。

当前新增测试：

```bash
python -m pytest tests/test_remote_adapters.py
```

覆盖内容：

- 使用本地 fake HTTP server 模拟远程 LLM。
- 校验 `RemoteLLMClient` 能发送 event 并解析候选记忆。
- 校验 `RemoteEmbeddingClient` 能解析 `vectors` 和 OpenAI-style `data[].embedding`。
- 校验 API `/remote/extract/{event_id}` 只做 dry-run，不自动写入候选表。
- 校验 API `/remote/route` 能把多条 event 分流为长期候选、短期会话记忆、忽略和拒绝；长期候选只进 pending，不自动 commit。
- 校验 API `/remote/evaluate-candidates` 对比本地与远程候选，但不写候选表。
- 校验 API `/memories/embeddings/remote-backfill` 能批量补齐缺失的向量缓存。
- 校验 API `/remote/evaluate-retrieval` 能用 fixture 对比 keyword / semantic / hybrid / guarded_hybrid，并可选加入 LLM judge。
- 校验 API `/memories/search/remote-guarded-hybrid` 能把低分或分差过小且无法被本地意图 rerank 确认的结果挡在最终返回前。
- 校验 API `/candidates/from-event/{event_id}/remote` 只写 pending candidate，不自动写入长期记忆。
- 校验 CLI `remote status` 不泄露 API key。
- 校验 CLI `remote route` 能读取多条 event 并调用远程分流。
- 校验 CLI `remote extract` 能读取本地 event 并调用 legacy 长期候选提取。
- 校验 CLI `remote evaluate` 能输出差异汇总且保持只读。
- 校验 CLI `remote import` 能把 legacy 远程候选写入本地候选队列。
- 校验 CLI `remote embed-backfill` 能批量写入 `memory_embeddings`。
- 校验 CLI `remote guarded-hybrid-search` 能输出 accepted / ambiguous / rejected 决策。
- 校验 CLI `remote evaluate-retrieval` 能输出 keyword / semantic / hybrid / guarded_hybrid，以及可选 `llm_guarded_hybrid` / `selective_llm_guarded_hybrid` 的 FN / unexpected / ambiguous / top1 统计。
- 校验敏感 event 在发起远程 HTTP 前被 preflight 跳过。
- 校验远程返回的敏感候选和闲聊偏好噪声会被本地治理过滤。
- 校验远程类型漂移会按高置信规则归一化为 `troubleshooting`、`environment_fact`、`workflow`、`project_fact` 或 `tool_rule`。
- 校验远程返回的低证据偏好不会被高置信写入，而是降级为 `ask_user`。
- 校验远程漏掉的低证据偏好可以由本地 fallback 生成 pending candidate，再交给写入门禁确认。

写入门禁的专门统计脚本：

```bash
python tools/evaluate_write_gate.py
python tools/evaluate_write_gate.py --sample-per-category 1
python tools/evaluate_write_gate.py --sample-per-category 1 --remote --failure-limit 10
python tools/evaluate_remote_local_conflicts.py --batch-size 10 --batches 5
```

这个脚本的本地模式只测试 `propose_memory -> evaluate_candidate`；远程写入门禁模式仍测试 legacy `RemoteLLMClient.extract_candidates -> create_candidate -> evaluate_candidate`，用于专门观察长期候选质量。当前推荐的真实对话入口则是 `RemoteLLMClient.route_memories -> long_term/session/ignore/reject/ask_user`，用于同时覆盖长期候选和短期会话记忆。因此它看的不是“召回能否想起记忆”，而是“某句话该不该形成候选、候选该写成什么类型、最终应该写入/确认/合并/拒绝，或只作为短期状态保留”。

`evaluate_remote_local_conflicts.py` 用固定随机种子抽样，把结果按批次输出为 `local_pass`、`remote_pass`、`local_better`、`remote_better` 和 `conflicts`。它用于发现远程输出和本地门禁的真实分歧；如果远程服务返回配额、网络或认证错误，应先排除这些错误，再比较模型准确率。

真实远程服务接入后，需要持续做人工标注小样本验收：

```text
同一批 event:
  本地 propose_memory
  远程 route_memories / legacy extract_candidates
  人工标注期望 memory_type / evidence_type / confidence
  对比误写率、漏召回率、平均延迟和失败率
```

当前 50 条只读远程统计结果：

```text
tp: 39
tn: 11
fp: 0
type_mismatch: 0
fn: 0
extra_noise: 0
skipped_sensitive_remote_calls: 4
avg_latency_ms_non_skipped: 14457.9
```

这组样本已经固化为 `tests/fixtures/golden_cases/remote_candidate_quality_50.jsonl`。默认测试只验证 fixture 形状、敏感 preflight 和高置信 fallback；真实远程统计需要显式开启：

```bash
$env:MEMORY_RUN_REMOTE_QUALITY = "1"
python -m pytest tests/test_remote_candidate_quality.py::test_remote_candidate_quality_live_fixture -s
```

这说明当前远程链路更偏高 precision：误写、类型漂移和已知 FN 都已被本地治理压住。扩大到几百条前，应沿用同一 fixture 结构，并继续让 live 远程质量测试默认跳过，避免普通回归测试依赖网络、额度和模型波动。

短期记忆分流的专门统计脚本：

```powershell
python tools\evaluate_session_route.py --fixture tests\fixtures\golden_cases\session_route.jsonl --sample-size 50 --sample-seed 20260430 --case-concurrency 4 --failure-limit 20 --report-path data\session_route_eval_50.json
python tools\evaluate_session_route.py --fixture tests\fixtures\golden_cases\session_route.jsonl --category en_session_pending_decision --category cn_ask_user_blocking_decision --category en_long_term_project_rule --case-concurrency 4 --failure-limit 20 --report-path data\session_route_eval_targeted.json
python tools\evaluate_session_route_splitting.py --fixture tests\fixtures\golden_cases\session_route_splitting.jsonl --case-concurrency 4 --failure-limit 20 --report-path data\session_route_splitting_eval_24.json
python tools\evaluate_task_boundary.py --fixture tests\fixtures\golden_cases\task_boundary.jsonl --case-concurrency 4 --failure-limit 20 --report-path data\task_boundary_eval_46.json
python tools\evaluate_session_closeout.py --fixture tests\fixtures\golden_cases\session_closeout.jsonl --sample-per-category 1 --sample-seed 20260430 --case-concurrency 4 --failure-limit 20 --report-path data\session_closeout_eval_16.json
```

这个脚本直接调用 `RemoteLLMClient.route_memories()`，用来检查“对话 event 应进入长期候选、短期 session、忽略、拒绝，还是先问用户”。`route_accuracy` 只看 long_term / session / ignore / reject / ask_user 主路由；`strict_accuracy` 还要求 `memory_type` 或 `session_memory_type` 完全一致。2026-04-30 同 seed 50 条真实远程验收结果为 route `50/50`、strict `42/50`、serious failures `0`，报告保存在 `data\session_route_eval_50_final.json`；定向边界集 `en_session_pending_decision + cn_ask_user_blocking_decision + en_long_term_project_rule` 为 route `30/30`、strict `26/30`、serious failures `0`，报告保存在 `data\session_route_eval_targeted_after_prompt.json`。剩余 strict mismatch 主要是 `scratch_note` vs `temporary_rule`、`workflow` vs `project_fact` 这类细分类漂移，不影响主路由。

`evaluate_session_route_splitting.py` 用同一次远程请求处理 case 内所有 events，并逐项匹配 expected item。2026-04-30 真实远程 24 条结果为 route case `24/24`、route item `57/57`、strict item `51/57`、serious failures `0`，报告保存在 `data\session_route_splitting_eval_24_final.json`。这说明当前模型已经能在复合输入中同时拆出长期和短期主路由；剩余 strict mismatch 主要是短期细分类漂移、workflow/project_fact 边界和少量重复 long_term 噪声。

`route_memories()` 现在也会请求观察型 `task_boundary`，输入可以包含 `current_task_state`、`recent_events` 和当前 session 记忆。这个字段用于判断 `same_task / new_task / switch_task / task_done / task_cancelled / unclear / no_change`，默认只解析、返回和记录，不自动切换任务。任务结束后的短期记忆整理由 `/session/closeout` 显式触发：LLM 逐条判断 `keep / discard / summarize / promote_candidate`，本地再执行 dismiss 或创建 pending candidate。2026-04-30 真实远程烟测中，当前任务为“短期记忆接入上下文”、最近消息建议“下一步做短期记忆生命周期管理”、用户回复“可以，那就进入生命周期这一步”时，模型返回 `switch_task/high`，`next_task_title=短期记忆生命周期管理`。

`evaluate_task_boundary.py` 是 `task_boundary` 专项统计脚本。它用 `task_boundary.jsonl` 检查当前任务子步骤是否保持 `same_task`，显式“接下来/换成/进入”是否切换，完成/取消/短确认是否进入对应边界。当前本地 boundary gate 已调整为 soft gate：只做结构规范化、明确完成/取消/切换兜底，以及弱证据 `switch_task/new_task` 降置信，不再靠本地子步骤关键词强制改判。2026-04-30 真实远程 46 条 soft gate 结果为 action `46/46`、strict `46/46`，报告保存在 `data\task_boundary_eval_soft_46_final.json`。

`evaluate_session_closeout.py` 是 `session_closeout` 专项统计脚本。它会把 fixture 中的短期记忆临时写入 `SessionMemoryStore`，用真实 id 调用 `RemoteLLMClient.closeout_session_memories()`，再按 alias 还原并统计 action accuracy、strict accuracy、candidate type mismatch、forbidden promotion、unsafe promotion 和 missing decisions。它测试的是“短期记忆如何退出或沉淀”，和 `evaluate_session_route.py` 测的“event 如何进入 session/long_term/ignore/reject/ask_user”不是同一环。2026-04-30 的 16 条分层真实远程 smoke 结果为 case `16/16`、action item `32/32`、strict item `32/32`、unsafe promotion `0`，报告保存在 `data\session_closeout_eval_16.json`。

API route 出来的 `session` 项会进入运行期 `SessionMemoryStore`，并在 `/context/compose` 和 `/recall/task` 中按 `session_id` 参与上下文组装。短期搜索会给 `pending_decision`、`temporary_rule`、`task_state`、`working_fact`、`emotional_state` 和 `scratch_note` 基础分，所以当前 session 的关键短期项不会因为 query 没有关键词重叠就被完全丢掉；最终注入数量仍由 `session_limit` 控制。

Embedding 检索当前有四组固定 fixture：

```text
tests/fixtures/golden_cases/semantic_retrieval.jsonl
tests/fixtures/golden_cases/generate_semantic_retrieval.py
tests/fixtures/golden_cases/semantic_retrieval_v2.jsonl
tests/fixtures/golden_cases/generate_semantic_retrieval_v2.py
tests/fixtures/golden_cases/semantic_retrieval_cn.jsonl
tests/fixtures/golden_cases/generate_semantic_retrieval_cn.py
tests/fixtures/golden_cases/semantic_retrieval_public.jsonl
tests/fixtures/golden_cases/generate_semantic_retrieval_public.py
```

这组样本专门观察“关键词可能想不起来，但 embedding 应该想起来”的情况。`remote evaluate-retrieval` 会同时跑 `keyword`、`semantic`、`hybrid` 和 `guarded_hybrid`；开启 `--llm-judge` 或 `--selective-llm-judge` 后，还会统计 LLM 复核后的召回结果。输出指标包括通过数、FN、unexpected alias、ambiguous 和 top-1 命中数。它适合先验证召回收益，再扩大到几百条或 2000 条综合样本。

`semantic_retrieval_v2.jsonl` 固定为 200 条：100 条技术/项目语义召回，80 条日常聊天偏好和习惯召回，20 条 no-match 场景。评测结果会额外包含 `category_summary`，用于观察某一类日常聊天或技术场景是否更容易 FN、误召回或 ambiguous。

`semantic_retrieval_cn.jsonl` 固定为 150 条：覆盖中文工程协作、调试、文档、编码、环境、git、记忆写入规则、召回规则、隐私边界、日常饮食、日程、回答风格、购物偏好，以及 daily/work no-match。它用 `*_target` 表示期望召回的目标记忆，用 `*_distractor_*` 表示干扰记忆；`expected.exact_aliases=[]` 表示该 case 应保持沉默。

`semantic_retrieval_public.jsonl` 固定为 300 条：参考 LongMemEval 的单轮/多轮/时间线/知识更新/拒答，LoCoMo 的日常长对话沉淀，以及 RealMemBench 的项目型目标、进展、决策和约束。它不复制外部数据集原文，只把公开 benchmark 的场景结构改写成本项目自己的合成样本。

公开数据集仿照样本评测命令：

```bash
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_cn.jsonl --selective-llm-judge --json
memoryctl --db data/memory.sqlite remote evaluate-retrieval --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --embedding-cache data/eval_embedding_cache.jsonl --report-path data/retrieval_report.json --case-concurrency 4 --judge-group-size 4 --judge-concurrency 2 --json
python tools/benchmark_remote_retrieval.py --fixture tests/fixtures/golden_cases/semantic_retrieval_public.jsonl --limit 60 --embedding-cache data/benchmark_remote_retrieval_embeddings.jsonl --output-dir data/remote_retrieval_benchmarks --case-concurrency 4
```

远程大样本评估默认应带 `--embedding-cache`。cache 按 text + model 记录 embedding 结果，第一次跑会写入，后续同模型重跑会命中；如果命令中途失败，直接用同一个 cache 重跑即可减少重复 embedding 调用。`--report-path` 会把完整 JSON 报告落盘，便于保留每次远程模型、阈值和 fixture 版本的统计结果。`--case-concurrency` 默认是 1，设为 3 或 4 时会并发预取 embedding 并并发处理 case，适合真实远程评估提速；case 阶段只做本地召回和 guard，不直接调用 DeepSeek。远程 judge 有独立并发和打包大小：`--judge-group-size 1 --judge-concurrency 4` 会并发发送多个单条 judge 请求；`--judge-group-size 2|4 --judge-concurrency 2` 会把需要远程复核的 uncertain case 分组交给 DeepSeek。报告中的 `metadata.judge` 会记录 pending task 数、group size、judge concurrency、single call 数、batch 数、实际 batch call 数和 fallback single 次数。

2026-04-29 真实远程 embedding / selective LLM 对比结果：

```text
v1 / 50 cases
keyword:        passed=24 failed=26 FN=26 unexpected=12 ambiguous=0 top1=24
semantic:       passed=41 failed=9  FN=9  unexpected=9  ambiguous=0 top1=41
hybrid:         passed=41 failed=9  FN=9  unexpected=9  ambiguous=0 top1=41
guarded_hybrid: passed=50 failed=0  FN=0  unexpected=0  ambiguous=0 top1=50
selective_llm_guarded_hybrid: passed=50 failed=0 FN=0 unexpected=0 ambiguous=0 top1=50

v2 / 200 cases
keyword:        passed=89  failed=111 FN=106 unexpected=41 ambiguous=0  top1=74
semantic:       passed=157 failed=43  FN=23  unexpected=43 ambiguous=0  top1=157
hybrid:         passed=157 failed=43  FN=23  unexpected=43 ambiguous=0  top1=157
guarded_hybrid: passed=173 failed=27  FN=7   unexpected=5  ambiguous=44 top1=173
selective_llm_guarded_hybrid: passed=194 failed=6 FN=1 unexpected=5 ambiguous=3 top1=179

cn / 150 cases
keyword:        passed=35  failed=115 FN=115 unexpected=0  ambiguous=0  top1=15
semantic:       passed=129 failed=21  FN=1   unexpected=21 ambiguous=0  top1=129
hybrid:         passed=129 failed=21  FN=1   unexpected=21 ambiguous=0  top1=129
guarded_hybrid: passed=127 failed=23  FN=3   unexpected=3  ambiguous=40 top1=127
selective_llm_guarded_hybrid: passed=149 failed=1 FN=0 unexpected=0 ambiguous=3 top1=130

public / 300 cases
keyword:        passed=164 failed=136 FN=97 unexpected=123 ambiguous=0  top1=163
semantic:       passed=247 failed=53  FN=13 unexpected=53  ambiguous=0  top1=247
hybrid:         passed=247 failed=53  FN=13 unexpected=53  ambiguous=0  top1=247
guarded_hybrid: passed=242 failed=58  FN=18 unexpected=18 ambiguous=80 top1=242

public / first 60 cases / selective LLM smoke
guarded_hybrid:               passed=54 failed=6 FN=6 unexpected=0 ambiguous=12 top1=54
selective_llm_guarded_hybrid: passed=57 failed=3 FN=3 unexpected=0 ambiguous=6  top1=57
```

这说明 embedding 显著降低漏召回；`guarded_hybrid` 会压低误召回，但会把 no-match 和近邻候选变成 ambiguous；`selective_llm_guarded_hybrid` 能进一步减少 ambiguous 和部分 FN。当前仍要重点优化 abstention/no-match 场景，以及长批量远程请求的网络稳定性。

## 11. 推荐验证顺序

不要一开始就验证“智能不智能”。先验证基本可靠性。

推荐顺序：

```text
1. 数据库写入读取
2. Event Log 可追溯
3. 写入门禁拒绝能力
4. confirmed 记忆提交能力
5. FTS 检索能力
6. scope 排序能力
7. 上下文注入能力
8. 冲突更新能力
9. 巩固和归档能力
10. 真实任务端到端效果
```

系统越早证明“不乱记”，后续才越值得让它自动化。
