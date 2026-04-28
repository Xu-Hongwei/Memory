# 规则判断文档

## 1. 判断目标

规则判断的目标不是“尽可能多写记忆”，而是保证系统长期运行后仍然干净、可信、可追溯。

当前判断原则：

```text
宁可少记，也不要污染记忆。
```

一条信息进入长期记忆前，必须同时回答：

- 是否长期有用
- 是否明确真实
- 是否非敏感
- 是否未来可复用
- 是否有来源事件
- 是否与已有记忆重复
- 是否与已有记忆冲突

## 2. 判断链路

完整链路：

```text
Event
  -> Candidate Extraction
  -> Local Governance
  -> Policy Evaluation
  -> Commit / Merge / Ask User / Reject
  -> Lifecycle Management
```

远程 LLM 只参与候选提取，不参与最终写入裁决。最终裁决以本地 `evaluate_candidate(...)` 和显式人工操作为准。

## 3. Event 层判断

事件类型：

```text
user_message
assistant_message
tool_result
file_observation
test_result
user_confirmation
```

Event Log 只负责保存必要证据，不直接判断是否写入长期记忆。

但事件进入系统时会做基础敏感处理：

- `[REDACTED]` 标记必须被视为高风险。
- token、secret、api key、password、cookie、bearer、authorization 等内容不应进入远程请求或长期记忆。
- 敏感内容即使被模型提取为候选，也必须被本地治理过滤。

## 4. 候选提取规则

候选记忆结构：

```text
content
memory_type
scope
subject
source_event_ids
reason
claim
evidence_type
time_validity
reuse_cases
scores.long_term
scores.evidence
scores.reuse
scores.risk
scores.specificity
confidence
risk
```

本地规则会优先识别这些正例：

| 场景 | 类型 | 条件 |
| --- | --- | --- |
| 用户明确说“以后 / 默认 / 记住 / 总是” | `user_preference` | 非临时、非敏感、可复用 |
| 用户说“喜欢” | `user_preference` | 必须指向回答、文档、代码、格式、语言、风格等可复用对象 |
| 已确认文件或工具观察 | `project_fact` | 来自 `file_observation`、`tool_result`、`test_result` |
| 问题 / 经验 / 解决方式，并验证通过 | `troubleshooting` | 问题真实发生，解决方式已验证 |
| 已确认运行环境状态 | `environment_fact` | 例如系统、shell、路径、编码、依赖状态 |
| 固定项目流程 | `workflow` | 可重复执行的 repo 流程、发布流程、验证流程 |
| 固定命令或工具规则 | `tool_rule` | 命令、工具调用、使用约束 |
| 明确设计取舍 | `decision` | 项目级或架构级长期决策 |

## 5. 直接拒绝规则

以下内容默认不写入长期记忆：

```text
一次性请求
临时状态
本轮任务限定
未经验证的猜测
普通闲聊
纯提问
情绪表达
敏感信息
失败但未解决的排错尝试
没有复用价值的信息
```

临时线索包括：

```text
这次
当前任务
本轮
今天先
先用
暂时
temporary
temporarily
临时用
临时把
临时先
临时记住
```

例外：

```text
“临时状态”作为被讨论的概念，不等于这条信息本身是临时请求。
```

## 6. 写入门禁决策

`evaluate_candidate(...)` 当前输出五种决策：

```text
write
reject
ask_user
merge
update
```

当前实际判断顺序：

1. 如果 `risk=high` 或内容包含 `[REDACTED]`，直接 `reject`。
2. 如果与 active 记忆在 `memory_type + scope + subject + content` 上完全重复，返回 `merge`。
3. 如果与 active 记忆在 `memory_type + scope + subject` 相同但内容不同，返回 `ask_user`。
4. 如果 `evidence_type=unknown` 或 `scores.evidence < 0.5`，返回 `ask_user`。
5. 如果 `scores.long_term < 0.5` 或 `scores.reuse < 0.4`，返回 `reject`。
6. 如果类型属于可自动写入类型，且 `confidence` 为 `confirmed` 或 `likely`，返回 `write`。
7. 如果 `confidence` 为 `inferred` 或 `unknown`，返回 `ask_user`。
8. 其他情况返回 `reject`。

可自动写入类型：

```text
user_preference
project_fact
tool_rule
environment_fact
troubleshooting
workflow
decision
```

`reflection` 当前不在自动写入白名单里，除非后续人工确认或策略扩展。

## 7. 冲突和重复判断

重复判断：

```text
active
+ same memory_type
+ same scope
+ same subject
+ same content
= merge
```

冲突判断：

```text
active
+ same memory_type
+ same scope
+ same subject
+ different content
= ask_user
```

当前冲突不会自动覆盖旧记忆。系统会要求确认：

```text
请确认应替换旧记忆、合并，还是保留为新的适用范围。
```

显式 update / supersede 发生时，旧记忆会变为 `superseded`，新记忆保持 `active`，并写入 `memory_versions`。

## 8. Commit 规则

只有以下情况可以提交长期记忆：

- policy decision 是 `write`
- policy decision 是 `merge`
- policy decision 是 `update`
- 人工显式 `approve_candidate(...)`

提交行为：

| decision | 行为 |
| --- | --- |
| `write` | 新建 active memory |
| `merge` | 不创建重复记忆，复用已有 active memory |
| `update` | 旧记忆 superseded，新候选写为 active |
| `ask_user` | 不允许直接 commit |
| `reject` | 不允许 commit |

## 9. 检索判断规则

默认检索只使用：

```text
status = active
```

可选过滤：

```text
scope
memory_type
retrieval_mode
limit
query_embedding
embedding_model
```

检索模式：

```text
keyword   关键词 / FTS / LIKE
semantic  远程 embedding 相似度
hybrid    关键词 + embedding
```

排序信号：

| 信号 | 作用 |
| --- | --- |
| FTS 命中 | 增加精确检索分 |
| query 出现在 content / subject | 增加强关键词分 |
| semantic score | 语义或混合检索核心分 |
| scope 命中 | 当前范围优先 |
| memory_type 命中 | 类型过滤优先 |
| confirmed / likely | 高置信优先 |
| updated_at | 同分时新记忆优先 |

## 10. Guarded Hybrid 判断

`guarded_hybrid` 用于解决“embedding 想起太多”的问题。

它会在 hybrid 结果后继续判断：

- 相似度太低：拒绝。
- 前几名分差太小：标记 ambiguous。
- 本地意图无法确认：标记 ambiguous。
- 结果明确且分数足够：accepted。

当前远程实测说明：

```text
semantic/hybrid 能显著减少 FN。
guarded_hybrid 能显著减少 unexpected。
但 no-match / abstention 场景还会产生较多 ambiguous 或误召回。
```

因此下一步规则优化重点是：

```text
当问题询问不存在的信息、敏感信息、私有身份信息、客户信息或未记录事实时，更强地返回空。
```

## 11. Recall Orchestrator 判断

`orchestrate_recall(...)` 是智能体使用记忆时的统一入口，规则目标是把“召回”和“注入”分开治理：

```text
task
  -> 判断是否需要记忆
  -> 选择 keyword / guarded_hybrid / selective_llm_guarded_hybrid
  -> 可选合并 graph recall
  -> no-match / skipped 判断
  -> context composer
  -> retrieval_logs(source=orchestrated_recall)
```

当前规则：

- `ok`、`谢谢` 等低记忆需求消息直接跳过召回，避免为了闲聊硬查长期记忆。
- 没有远程客户端时走本地 `RecallPlanner + keyword search`。
- 有 remote embedding 时走 `guarded_hybrid`，先压低低分和歧义召回。
- 有 remote embedding 和 remote LLM 时走 `selective_llm_guarded_hybrid`，只在本地 guard 不够可靠或具体事实风险较高时请求 LLM 二次判断。
- 图谱召回只能作为补充来源，不能绕过 `active`、scope、confidence 和上下文预算。
- 最终日志必须区分 `retrieved_memory_ids`、`used_memory_ids`、`skipped_memory_ids`，便于后续反馈、降权和遗忘。

## 12. 上下文注入规则

上下文组装只注入 `active` 记忆。

会产生 warning 的情况：

```text
status != active
confidence != confirmed
missing last_verified_at
token_budget exhausted
```

注入内容包括：

```text
confidence
memory_type
scope
subject
content
source_event_ids
```

上下文组装的目标不是把所有相关记忆都塞进去，而是在预算内优先保留最可信、最相关、最当前的记忆。

## 13. 生命周期规则

生命周期动作：

```text
mark_stale
archive_memory
supersede_memory
commit_consolidation
resolve_conflict_review
resolve_maintenance_review
```

规则：

- `active -> stale` 后不再默认检索。
- `active/stale -> archived` 后只保留历史。
- `active/stale -> superseded` 后由新记忆替代。
- 所有状态变化都写入 `memory_versions`。
- 旧记忆不物理删除，方便审计和回放。

## 14. 巩固规则

自动巩固只处理：

```text
status = active
confidence in confirmed / likely
same scope
same memory_type
same subject
```

巩固流程：

```text
active memories
  -> consolidation candidate
  -> manual/API commit
  -> new consolidated memory active
  -> source memories superseded
```

低置信、跨 scope、不同类型、inactive 记忆不参与自动巩固。

## 15. 图谱规则

图谱当前是轻量层，用于辅助召回和冲突发现。

实体类型：

```text
repo
file
tool
command
error
solution
preference
module
concept
unknown
```

图谱召回规则：

- 从任务文本和当前 scope 找 seed entities。
- 沿 confirmed / likely 关系查找 source memories。
- 仍然只注入 active 记忆。
- 其他 repo 的实体关系不串入当前 repo。

图谱冲突规则：

```text
same from entity
+ same relation type
+ multiple active targets
= conflict review
```

例如同一个 repo 同时指向两个不同启动命令，就需要 review。

## 16. 远程 LLM 治理规则

远程 LLM 提取候选时，本地会给出治理提示，并在返回后再次过滤。

优先级：

1. `[REDACTED]` / token / secret / api key / password / cookie / bearer / authorization 相关内容不提候选。
2. “问题 / 经验 / 解决方式 / 验证通过”强制优先 `troubleshooting`。
3. 已确认环境状态优先 `environment_fact`。
4. 项目固定流程优先 `workflow`。
5. 已验证文件或文档观察优先 `project_fact`。
6. 固定命令或工具使用规则优先 `tool_rule`。

远程候选不会直接写入长期记忆。即使导入，也只是 pending candidate。

## 17. 黄金测试对规则的约束

规则判断必须持续通过黄金测试集。

关键测试：

```powershell
python tests\fixtures\golden_cases\audit_golden_cases.py --strict
python -m pytest tests\test_golden_write_policy.py -q
python -m pytest tests\test_golden_retrieval_context.py -q
python -m pytest tests\test_golden_lifecycle.py -q
python -m pytest tests\test_golden_task_recall.py -q
python -m pytest tests\test_recall_orchestrator.py -q
python -m pytest tests\test_golden_consolidation.py -q
python -m pytest tests\test_golden_graph_recall.py -q
python -m pytest tests\test_golden_graph_conflicts.py -q
python -m pytest tests\test_golden_conflict_reviews.py -q
python -m pytest tests\test_remote_adapters.py -q
```

规则修改后的判断标准：

- 不能提高敏感信息写入风险。
- 不能让一次性请求更容易进入长期记忆。
- 不能让 inactive 记忆重新进入默认召回。
- 不能让远程结果绕过本地治理。
- 如果提升召回率，必须同时观察 unexpected 和 ambiguous。
