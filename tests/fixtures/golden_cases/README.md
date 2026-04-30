# Golden Case Fixtures

这个目录保存记忆系统的固定测试数据和生成脚本。这里的 JSONL 不是线上用户数据，也不是直接复制的网络语料，而是用脚本生成的可复现实验样本，用来验证写入策略、召回、上下文组装、生命周期、整合、图谱关系、冲突判断和远程模型链路。

## 基本原则

- 优先改生成脚本，再重新生成 JSONL，避免手工改样本导致脚本和数据漂移。
- 所有 JSONL 使用 UTF-8 编码。Windows PowerShell 预览无 BOM UTF-8 文件时可能显示乱码，真实内容以 Python `encoding="utf-8"` 读取为准。
- 每条 case 的 `name` 必须唯一。
- 普通黄金集应尽量避免重复输入文本和重复 memory content。
- `semantic_retrieval.jsonl`、`semantic_retrieval_v2.jsonl`、`semantic_retrieval_cn.jsonl` 和 `semantic_retrieval_public.jsonl` 允许重复 memory content，因为它们刻意用“同一条记忆 + 多种改写问法”测试语义召回是否能想起正确记忆。重复的是被测记忆，不是重复 case。
- 敏感信息、真实 token、真实密钥和真实私有数据不应该进入 fixture。

## 目录索引

| 文件 | 生成脚本 | 规模 | 用途 |
| --- | --- | ---: | --- |
| `write_policy.jsonl` | `generate_write_policy.py` | 2000 | 判断用户输入是否应该写入长期记忆，以及应该写成什么类型 |
| `write_policy_time_validity.jsonl` | manual fixture | 16 | 专测 `time_validity` 门禁：`persistent` / `until_changed` 应写入，`session` 应拒绝，`unknown` 应转人工确认 |
| `write_policy_cn_realistic.jsonl` | `generate_write_policy_cn_realistic.py` | 800 | 中文真实表达补充集，覆盖低证据偏好、泛化不足偏好、日常喜欢反例、排错、流程、环境事实、重复和冲突 |
| `write_policy_en_realistic.jsonl` | `generate_write_policy_en_realistic.py` | 800 | 英文真实表达补充集，覆盖英文长期偏好、低证据偏好、拒写表达、临时请求、排错、流程、环境事实、重复和冲突 |
| `session_route.jsonl` | `generate_session_route.py` | 240 | 短期记忆分流测试集，覆盖 session/ignore/long_term/reject/ask_user，以及 6 类 session memory type |
| `session_route_splitting.jsonl` | `generate_session_route_splitting.py` | 24 | 多信息分流测试集，覆盖单句多原子项和多 event 批量输入下的 long_term/session/ask_user/reject 差分 |
| `task_boundary.jsonl` | `generate_task_boundary.py` | 46 | 任务边界判断测试集，覆盖 same_task 子步骤、显式切换、完成、取消、短确认和承接下一步 |
| `session_closeout.jsonl` | `generate_session_closeout.py` | 160 | 短期记忆收尾测试集，覆盖任务完成、取消、切换、待决保留、摘要、升级长期候选和敏感过滤 |
| `retrieval_context.jsonl` | `generate_retrieval_context.py` | 400 | 本地检索/上下文机制回归，测试 scope、类型过滤、inactive 过滤、排序、预算裁剪和 warning；不作为真实语义召回基准 |
| `lifecycle.jsonl` | `generate_lifecycle.py` | 300 | 测试 active/stale/archived 等生命周期状态 |
| `task_recall.jsonl` | `generate_task_recall.py` | 300 | 测试一句任务/query 能召回哪些相关记忆 |
| `consolidation.jsonl` | `generate_consolidation.py` | 300 | 测试重复、补充、冲突、过期记忆的整合策略 |
| `graph_recall.jsonl` | `generate_graph_recall.py` | 300 | 测试知识图谱关系召回 |
| `graph_conflicts.jsonl` | `generate_graph_conflicts.py` | 300 | 测试知识图谱中的关系冲突和更新 |
| `conflict_reviews.jsonl` | `generate_conflict_reviews.py` | 300 | 测试冲突候选的人工复核/模型复核输入 |
| `remote_candidate_quality_50.jsonl` | 手工固化小样本 | 50 | 小规模远程 LLM 写入候选质量统计 |
| `semantic_retrieval.jsonl` | `generate_semantic_retrieval.py` | 50 | v1 语义召回小样本，用于比较 keyword/semantic/hybrid/guarded_hybrid |
| `semantic_retrieval_v2.jsonl` | `generate_semantic_retrieval_v2.py` | 200 | v2 语义召回样本，加入更多日常聊天、no-match 和分类统计 |
| `semantic_retrieval_cn.jsonl` | `generate_semantic_retrieval_cn.py` | 150 | 中文真实语义召回样本，覆盖工程协作、记忆规则、隐私边界、日常偏好和 no-match |
| `semantic_retrieval_public.jsonl` | `generate_semantic_retrieval_public.py` | 300 | 参考 LongMemEval、LoCoMo 和 RealMemBench 场景结构生成的 public-inspired 语义召回样本 |

## 如何重新生成

在项目根目录运行：

```powershell
python tests\fixtures\golden_cases\generate_write_policy.py
python tests\fixtures\golden_cases\generate_write_policy_cn_realistic.py
python tests\fixtures\golden_cases\generate_write_policy_en_realistic.py
python tests\fixtures\golden_cases\generate_session_route.py
python tests\fixtures\golden_cases\generate_task_boundary.py
python tests\fixtures\golden_cases\generate_session_closeout.py
python tests\fixtures\golden_cases\generate_retrieval_context.py
python tests\fixtures\golden_cases\generate_lifecycle.py
python tests\fixtures\golden_cases\generate_task_recall.py
python tests\fixtures\golden_cases\generate_consolidation.py
python tests\fixtures\golden_cases\generate_graph_recall.py
python tests\fixtures\golden_cases\generate_graph_conflicts.py
python tests\fixtures\golden_cases\generate_conflict_reviews.py
python tests\fixtures\golden_cases\generate_semantic_retrieval.py
python tests\fixtures\golden_cases\generate_semantic_retrieval_v2.py
python tests\fixtures\golden_cases\generate_semantic_retrieval_cn.py
python tests\fixtures\golden_cases\generate_semantic_retrieval_public.py
python tests\fixtures\golden_cases\generate_session_route_splitting.py
```

生成后建议立刻跑一次重复审计和相关测试：

```powershell
python tests\fixtures\golden_cases\audit_golden_cases.py
python tests\fixtures\golden_cases\audit_golden_cases.py --strict
python tests\fixtures\golden_cases\audit_golden_cases.py --show-template-groups 5
python -m pytest tests\test_golden_write_policy.py tests\test_golden_write_policy_cn_realistic.py tests\test_golden_write_policy_en_realistic.py tests\test_golden_session_route.py tests\test_golden_session_route_splitting.py tests\test_golden_task_boundary.py tests\test_golden_session_closeout.py tests\test_golden_retrieval_context.py tests\test_golden_lifecycle.py tests\test_golden_task_recall.py tests\test_golden_consolidation.py tests\test_golden_graph_recall.py tests\test_golden_graph_conflicts.py tests\test_golden_conflict_reviews.py tests\test_remote_adapters.py -q
```

`--strict` 会允许 semantic retrieval 四个 fixture 的 memory content 重复，也允许 `write_policy.jsonl` 的 `merge_duplicate` / `ask_conflict` 类别，以及 `write_policy_en_realistic.jsonl` 的 `en_merge_duplicate` / `en_ask_conflict` 类别复用同一事实。除此之外，重复 case name、重复输入文本、重复 memory content 会被视为异常。

`--show-template-groups N` 会额外展示“只替换编号后看起来相同”的模板化重复。这个检查不会直接判定失败，因为有些重复是刻意构造的边界测试；但如果 `template_dup_texts` 很高，说明样本规模可能虚胖，不能把行数直接等同于语义覆盖。

`write_policy.jsonl` 现在要求更严格：2000 条事件文本必须 exact 唯一，并且去掉编号后仍然唯一；`existing_memories` 也必须满足同样约束。这个约束已经写入 `tests/test_golden_write_policy.py`，用于防止用编号堆样本。

`write_policy_cn_realistic.jsonl` 进一步要求 800 条事件文本全部唯一且包含中文字符，并且每条 case 都带有 `scenario`、`utterance_style` 和 `source_family` 标注。它的目标不是继续堆模板数量，而是补足真实中文口语边界：例如“也许我更喜欢...”应进入 `ask_user`，而“我喜欢这个按钮圆角，不代表以后都要这样”不应进入长期记忆。当前这组补充集覆盖 213 个场景标签、28 种表达风格和 6 个来源族，`audit_golden_cases.py --strict` 下不应出现 unexpected duplicate，输入文本的模板化重复也应保持为 0。

`write_policy_en_realistic.jsonl` 要求 800 条事件文本全部唯一且包含英文字母，并且不包含中文字符。它同样带有 `scenario`、`utterance_style` 和 `source_family` 标注。当前这组补充集覆盖 193 个场景标签、28 种表达风格和 6 个来源族，用来约束 `going forward`、`maybe I prefer`、`do not treat this as a preference`、`for this run`、`Problem / Lesson / Solution / Verified` 等英文写入边界。

`session_route.jsonl` 固定为 240 条，专门测试远程分流阶段是否能把 event 路由到 `session`、`ignore`、`long_term`、`reject` 或 `ask_user`。其中 `session` 样本覆盖 `task_state`、`temporary_rule`、`working_fact`、`pending_decision`、`emotional_state` 和 `scratch_note` 六类；`ignore` 覆盖简单确认和低价值闲聊；`long_term` 用作长期偏好/固定流程对照；`reject` 使用 `[REDACTED]` 占位符测试敏感 preflight；`ask_user` 覆盖当前必须先确认再继续的阻塞决策。默认测试只做 fixture 结构和本地 fallback 子集校验，不依赖真实远程模型。

`session_route_splitting.jsonl` 固定为 24 条，专门补足单句多信息和多 event 批量输入场景。每条 case 至少包含一个 `long_term` 和一个 `session` expected item，部分 case 额外包含 `ask_user` 或 `reject`，用于检查远程模型是否会把复合信息拆成多个原子 route item，而不是只选一个主路由。

`task_boundary.jsonl` 固定为 46 条，专门测试 `route_memories()` 返回的观察型 `task_boundary`。它把“测试一下、验证一下、举例、同步文档、修一下”这类当前任务子步骤和“接下来做 X、换成 X、这部分完成/取消”这类真正边界分开。当前本地 boundary gate 是 soft gate：不再靠子步骤关键词强制改判，只兜底明确完成/取消/切换和弱证据降置信。

`session_closeout.jsonl` 固定为 160 条，专门测试任务结束、取消、切换或仍待确认时，已有短期记忆应被 `keep / discard / summarize / promote_candidate` 如何收尾。每条 case 包含 2 条 session memory，并用 alias 对齐预期动作；敏感样本只使用 `[REDACTED]` 占位，允许被远程 preflight 过滤成 `missing`，但禁止升级为长期候选。

## 如何使用

本地规则和结构校验：

```powershell
python -m pytest tests\test_golden_write_policy.py -q
python -m pytest tests\test_golden_write_policy_time_validity.py -q
python -m pytest tests\test_golden_write_policy_cn_realistic.py -q
python -m pytest tests\test_golden_write_policy_en_realistic.py -q
python -m pytest tests\test_golden_session_route.py -q
python -m pytest tests\test_golden_session_route_splitting.py -q
python -m pytest tests\test_golden_session_closeout.py -q
python -m pytest tests\test_golden_retrieval_context.py -q
python -m pytest tests\test_golden_lifecycle.py -q
python -m pytest tests\test_golden_task_recall.py -q
python -m pytest tests\test_golden_consolidation.py -q
python -m pytest tests\test_golden_graph_recall.py -q
python -m pytest tests\test_golden_graph_conflicts.py -q
python -m pytest tests\test_golden_conflict_reviews.py -q
```

写入门禁统计：

```powershell
python tools\evaluate_write_gate.py
python tools\evaluate_write_gate.py --sample-per-category 1
python tools\evaluate_write_gate.py --sample-size 50 --sample-seed 20260429 --remote --case-concurrency 4 --failure-limit 10
python tools\evaluate_remote_local_conflicts.py --batch-size 10 --batches 5
```

`evaluate_write_gate.py` 默认读取 `write_policy.jsonl`、`write_policy_time_validity.jsonl`、`write_policy_cn_realistic.jsonl` 和 `write_policy_en_realistic.jsonl`。本地模式只验证规则候选与门禁决策；`--remote` 会把同一批样本先交给远程模型提候选，再用本地门禁判断 `write / ask_user / merge / reject`，适合统计远程模型是少误写、多漏提，还是会引入噪声。远程模式支持 `--case-concurrency`，含义和召回评估里的第一层并发一致：同时跑多少条 case，每条 case 各自完成 LLM 候选提取和本地 gate。

`evaluate_remote_local_conflicts.py` 会固定随机抽样并按批次输出本地与 `remote_after_gate` 的差异，适合复测远程模型是否和本地门禁冲突。它依赖真实远程额度；如果远程服务返回配额或网络错误，这部分结果只能说明远程不可用，不能当成模型质量统计。

短期记忆分流统计：

```powershell
python tools\evaluate_session_route.py --fixture tests\fixtures\golden_cases\session_route.jsonl --sample-size 50 --sample-seed 20260430 --case-concurrency 4 --failure-limit 20 --report-path data\session_route_eval_50.json
python tools\evaluate_session_route.py --fixture tests\fixtures\golden_cases\session_route.jsonl --category en_session_pending_decision --category cn_ask_user_blocking_decision --category en_long_term_project_rule --case-concurrency 4 --failure-limit 20 --report-path data\session_route_eval_targeted.json
python tools\evaluate_session_route_splitting.py --fixture tests\fixtures\golden_cases\session_route_splitting.jsonl --case-concurrency 4 --failure-limit 20 --report-path data\session_route_splitting_eval_24.json
python tools\evaluate_task_boundary.py --fixture tests\fixtures\golden_cases\task_boundary.jsonl --case-concurrency 4 --failure-limit 20 --report-path data\task_boundary_eval_46.json
python tools\evaluate_session_closeout.py --fixture tests\fixtures\golden_cases\session_closeout.jsonl --sample-per-category 1 --sample-seed 20260430 --case-concurrency 4 --failure-limit 20 --report-path data\session_closeout_eval_16.json
```

`evaluate_session_route.py` 直接测试 `RemoteLLMClient.route_memories()` 的真实远程分流结果，统计 route accuracy、strict accuracy、serious failures 和按 category 的细分表现。route accuracy 看主路由是否正确，也就是 long_term / session / ignore / reject / ask_user 是否分对；strict accuracy 还会要求长期 `memory_type` 或短期 `session_memory_type` 完全命中。当前同 seed 50 条远程验收结果是 route `50/50`、strict `42/50`、serious `0`；剩余 strict mismatch 主要是 `scratch_note` vs `temporary_rule`、`workflow` vs `project_fact` 这类细分类漂移。

`evaluate_session_route_splitting.py` 用同一次远程请求处理 case 内全部 events，并按 expected item 逐项匹配实际 route item。2026-04-30 的 24 条真实远程验收结果为 route case `24/24`、route item `57/57`、strict item `51/57`、serious `0`；剩余问题主要是短期细分类漂移和少量重复 long_term 噪声。

`evaluate_task_boundary.py` 直接测试 `RemoteLLMClient.route_memories()` 返回的 `task_boundary`。2026-04-30 的 46 条真实远程 soft gate 验收结果为 action `46/46`、strict `46/46`，报告保存在 `data\task_boundary_eval_soft_46_final.json`。

`evaluate_session_closeout.py` 直接测试 `RemoteLLMClient.closeout_session_memories()`。它会临时创建 `SessionMemoryStore`，把 fixture 中的 alias 映射到真实 session memory id，再统计 action accuracy、strict accuracy、candidate type mismatch、forbidden promotion、unsafe promotion、missing decisions 和按 category 的表现。2026-04-30 的 16 条分层真实远程 smoke 结果为 case `16/16`、action item `32/32`、strict item `32/32`、unsafe promotion `0`，报告保存在 `data\session_closeout_eval_16.json`。

`retrieval_context.jsonl` 的定位要和语义召回集分开看：它是 plumbing regression，也就是保底层机制不坏。里面的 `RET_SCOPE_000`、`CONTEXT_WARN_029` 这类标记是人工唯一标识，目的是稳定验证 scope 优先级、类型过滤、inactive 排除、上下文预算和 warning。它不证明系统能理解真实自然语言；真实语义召回应优先看 `semantic_retrieval_cn.jsonl`、`semantic_retrieval_v2.jsonl` 和 `semantic_retrieval_public.jsonl`。

远程候选质量小样本：

```powershell
memoryctl --db data\memory.sqlite remote evaluate-candidates --fixture tests\fixtures\golden_cases\remote_candidate_quality_50.jsonl
```

语义召回 v1/v2/cn/public 对比：

```powershell
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval.jsonl
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_v2.jsonl
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_cn.jsonl --selective-llm-judge
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_public.jsonl
memoryctl --db data\memory.sqlite remote evaluate-retrieval --fixture tests\fixtures\golden_cases\semantic_retrieval_public.jsonl --embedding-cache data\eval_embedding_cache.jsonl --report-path data\retrieval_report.json --case-concurrency 4 --judge-group-size 4 --judge-concurrency 2
python tools\benchmark_remote_retrieval.py --fixture tests\fixtures\golden_cases\semantic_retrieval_public.jsonl --limit 60 --embedding-cache data\benchmark_remote_retrieval_embeddings.jsonl --output-dir data\remote_retrieval_benchmarks --case-concurrency 4
```

当前远程召回评估支持 split-provider 配置：LLM 可走 `LLM_REMOTE_*` / `DEEPSEEK_*`，embedding 可走 `EMBEDDING_REMOTE_*` / `DASHSCOPE_*`。如果只配置了 DeepSeek 和 DashScope，CLI 会自动把 LLM 请求发给 DeepSeek，把 embedding 请求发给 DashScope multimodal embedding。

扩大到几百条样本或真实远程模型时，建议固定使用 `--embedding-cache`、`--report-path` 和适度的 `--case-concurrency`。前者让同一批 text + model 的 embedding 可复用，命令中断后可直接重跑；后者保存完整 summary、category_summary、items、warnings 和 metadata，方便把不同模型或阈值的结果做 diff；`case_concurrency` 控制并发预取和 case 评估，真实远程建议先用 3 或 4。case 阶段只做本地召回和 guard；DeepSeek judge 后置调度，可以单独设置 `--judge-group-size 1 --judge-concurrency 4` 做并发单条复核，或 `--judge-group-size 2|4 --judge-concurrency 2` 做批量复核对照。

`evaluate-retrieval` 会同时比较：

- `keyword`
- `semantic`
- `hybrid`
- `guarded_hybrid`
- 可选 `llm_guarded_hybrid`
- 可选 `selective_llm_guarded_hybrid`

重点看这些指标：

- `FN`: 应该召回但没有召回。
- `unexpected`: 不该召回但召回了，代表噪声。
- `ambiguous`: guard 认为候选太接近，宁可不返回。
- `top1`: 第一名是否命中预期记忆。
- `category_summary`: 按场景类别看哪类样本最容易出错。

## 字段和代号约定

JSONL 中的 `alias` 是测试稳定代号，不是业务真实 ID。每条 case 会临时创建一个小型记忆库，测试结束后丢弃，所以真实数据库 ID 每次都可能变化；`alias` 用来让 fixture 稳定表达“哪条应该被召回”。

常见约定：

- `*_target`: 该 case 的正确目标记忆，通常应该被召回。
- `*_distractor_a` / `*_distractor_b`: 干扰记忆，通常不应该被召回。
- `expected.ordered_prefix`: 结果开头应该按顺序出现的 alias。
- `expected.exact_aliases`: 结果必须精确等于这些 alias；空数组表示 no-match，应该不返回任何记忆。
- `expected.absent_aliases`: 这些 alias 不应该出现在结果里。

例如 `cn_release_000_target` 和它的 `content` 绑定在同一个 memory 对象上：

```json
{
  "alias": "cn_release_000_target",
  "content": "发布前的固定流程是先跑 ruff，再跑 pytest，最后做一次关键路径冒烟验证。"
}
```

这表示测试期望系统在看到“上线前我应该先确认哪些检查？”时，召回这条发布前检查记忆，而不是召回同一 case 里的 debug 干扰项。

## 关于重复内容

看到重复内容时先分两类：

1. 低价值重复：同一个输入或同一条记忆被无意义复制，通常应该改生成脚本。
2. 有意复用：同一条稳定记忆被多种 query 改写触发，用来测试“说法变了还能不能想起来”。

当前主要有两种有意重复：

- `semantic_retrieval.jsonl`、`semantic_retrieval_v2.jsonl`、`semantic_retrieval_cn.jsonl` 和 `semantic_retrieval_public.jsonl` 会复用 memory content。它们每一行都会临时种入一组小型 memory，所以相同 content 出现在不同 case 里，不代表同一个测试环境中重复写入多份记忆。
- `write_policy.jsonl` 的 `merge_duplicate` 类别会复用输入事实，用来验证同一事实再次出现时应该合并已有记忆，而不是创建重复记忆。
- `write_policy.jsonl` 的 `ask_conflict` 类别会复用旧事实和新事实模板，用来验证冲突检测是否稳定。

还要特别留意“模板化重复”：例如只把 `样本 001` 改成 `样本 002`。这类内容不是完全重复，但对模型判断的新增信息很少。扩充黄金集时，应优先增加新的语义场景、表达方式和干扰项，而不是只增加编号。

如果以后扩展 v2，建议优先增加：

- 更多日常聊天场景，例如饮食、作息、通知、计划、旅行、购物和回答风格。
- 更多 no-match 场景，专门验证不该想起任何记忆时是否能保持沉默。
- 更细的 category，方便定位 FN、unexpected 和 ambiguous 的来源。
- 适量 content variant，避免语料看起来过于机械。
