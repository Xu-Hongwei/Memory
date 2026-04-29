# 10. 黄金测试集具体样例说明

这份文档专门解释黄金测试集里的“具体内容”到底是什么。

先说清楚一个边界：

```text
黄金测试集里的事实，大多是 synthetic test facts。
它们存在于测试文件中，但不代表现实项目真的存在这些事实。
```

也就是说：

- `repo:C:/workspace/alpha` 不一定是真实项目。
- `pnpm dev`、`npm run dev`、`Node 18` 等内容不一定是真实环境事实。
- 它们是为了测试记忆系统行为而构造的样本。

测试真正验证的是：

```text
系统在这些输入下，是否做出正确行为。
```

fixture 里的 `alias` 是测试用稳定代号，不是真实业务 ID。每条 case 会临时种入一组小型记忆，真实数据库 ID 每次测试都可能变化，所以测试用 `alias` 来表达预期行为：

```text
*_target        该 case 期望召回的目标记忆
*_distractor_*  干扰项，通常不应该召回
ordered_prefix  结果开头应该按顺序出现的 alias
exact_aliases   结果必须精确等于这些 alias；空数组表示 no-match
absent_aliases  不应该出现在结果里的 alias
```

## 1. 写入测试样例

来源：

```text
tests/fixtures/golden_cases/write_policy.jsonl
tests/fixtures/golden_cases/write_policy_cn_realistic.jsonl
tests/fixtures/golden_cases/write_policy_en_realistic.jsonl
```

### 1.1 应该写入长期偏好

样本：

```json
{
  "name": "positive_user_preference_000",
  "category": "positive_user_preference",
  "event": {
    "event_type": "user_message",
    "content": "以后回答默认使用中文，并清楚区分事实和推断。",
    "source": "conversation",
    "scope": "global"
  },
  "expected": {
    "candidates": [
      {
        "memory_type": "user_preference",
        "evidence_type": "direct_user_statement",
        "decision": "write",
        "commit": true
      }
    ]
  }
}
```

它在测试：

```text
用户明确说“以后/默认”时，系统应该把它识别为长期偏好。
```

期望结果：

```text
生成 user_preference 候选
证据类型是 direct_user_statement
写入长期记忆
```

### 1.2 不应该写入日常喜欢表达

样本类似：

```json
{
  "category": "negative_casual_like",
  "event": {
    "event_type": "user_message",
    "content": "我喜欢这首歌的节奏。"
  },
  "expected": {
    "candidates": []
  }
}
```

它在测试：

```text
“我喜欢这首歌”只是日常表达，不是长期协作偏好。
```

期望结果：

```text
不生成长期记忆候选
```

### 1.3 中文低证据偏好应该确认

样本类似：

```json
{
  "category": "cn_review_preference_uncertain",
  "event": {
    "event_type": "user_message",
    "content": "也许我更喜欢回答先给结论，再展开原因。"
  },
  "expected": {
    "candidates": [
      {
        "memory_type": "user_preference",
        "evidence_type": "direct_user_statement",
        "decision": "ask_user"
      }
    ]
  }
}
```

它在测试：

```text
“也许我更喜欢”是偏好信号，但证据不够强，不能直接写入。
```

期望结果：

```text
生成 user_preference 候选
决策为 ask_user
等待用户确认后再写入长期记忆
```

## 2. 召回测试样例

来源：

```text
tests/fixtures/golden_cases/retrieval_context.jsonl
```

### 2.1 当前 repo scope 优先

样本：

```json
{
  "name": "retrieval_current_scope_priority_000",
  "category": "retrieval_current_scope_priority",
  "memories": [
    {
      "alias": "scope_repo_000",
      "content": "RET_SCOPE_000 start command for alpha repo is pnpm dev.",
      "memory_type": "project_fact",
      "scope": "repo:C:/workspace/alpha",
      "status": "active",
      "confidence": "confirmed"
    },
    {
      "alias": "scope_global_000",
      "content": "RET_SCOPE_000 default start command guidance is npm run dev.",
      "memory_type": "project_fact",
      "scope": "global",
      "status": "active",
      "confidence": "confirmed"
    },
    {
      "alias": "scope_other_000",
      "content": "RET_SCOPE_000 start command for beta repo is yarn dev.",
      "memory_type": "project_fact",
      "scope": "repo:C:/workspace/beta",
      "status": "active",
      "confidence": "confirmed"
    }
  ],
  "search": {
    "query": "RET_SCOPE_000",
    "scopes": ["repo:C:/workspace/alpha", "global"],
    "memory_types": ["project_fact"],
    "limit": 2
  },
  "expected": {
    "ordered_prefix": ["scope_repo_000", "scope_global_000"],
    "absent_aliases": ["scope_other_000"]
  }
}
```

这里的 `RET_SCOPE_000` 是人为放进去的唯一标识，方便测试精确命中。
`retrieval_context.jsonl` 属于本地检索/上下文机制回归集，重点验证 scope、类型过滤、inactive 排除、排序和上下文 warning，不用于证明真实语义召回能力。

它在测试：

```text
同一个问题下，当前 repo 的记忆应该优先于 global。
其他 repo 的记忆不能串进来。
```

期望结果：

```text
第 1 条返回 scope_repo_000
第 2 条返回 scope_global_000
不返回 scope_other_000
```

### 2.2 上下文预算不足时跳过长记忆

样本：

```json
{
  "name": "context_budget_029",
  "category": "context_budget",
  "context": {
    "input_aliases": ["context_short_029", "context_long_029"],
    "task": "CONTEXT_BUDGET_029 assemble context",
    "token_budget": 260
  },
  "expected": {
    "included_aliases": ["context_short_029"],
    "excluded_aliases": ["context_long_029"],
    "warning_contains": ["token_budget exhausted"]
  }
}
```

它在测试：

```text
上下文空间不够时，短记忆可以注入，超长记忆不能硬塞进去。
```

期望结果：

```text
注入 context_short_029
跳过 context_long_029
产生 token_budget exhausted warning
```

## 3. 自然语言任务召回样例

来源：

```text
tests/fixtures/golden_cases/task_recall.jsonl
```

这一组比普通召回测试更接近真实智能体使用方式。它不是直接给 `query / memory_type / scope`，而是给一句任务：

```text
帮我写这个项目的启动说明 README
```

然后测试系统是否能自动规划：

```text
intent = documentation
memory_types = user_preference / project_fact / tool_rule / workflow
scopes = 当前 repo + global
query_terms = 文档 / README / 启动 / start command ...
```

### 3.1 写启动说明时应该想起什么

样本类似：

```json
{
  "name": "startup_docs_recall_000",
  "category": "startup_docs_recall",
  "synthetic": true,
  "task": "TASK_STARTUP_DOCS_000 帮我写这个项目的启动说明 README",
  "scope": "repo:C:/workspace/task-recall",
  "memories": [
    {
      "alias": "startup_doc_style_000",
      "content": "TASK_STARTUP_DOCS_000 documentation style uses Chinese and conclusion-first structure.",
      "memory_type": "user_preference",
      "scope": "global"
    },
    {
      "alias": "startup_command_000",
      "content": "TASK_STARTUP_DOCS_000 start command is pnpm dev.",
      "memory_type": "project_fact",
      "scope": "repo:C:/workspace/task-recall"
    },
    {
      "alias": "startup_other_repo_000",
      "content": "TASK_STARTUP_DOCS_000 start command for another repo is yarn dev.",
      "memory_type": "project_fact",
      "scope": "repo:C:/workspace/other-task"
    }
  ],
  "expected": {
    "intent": "documentation",
    "included_aliases": [
      "startup_doc_style_000",
      "startup_command_000"
    ],
    "excluded_aliases": [
      "startup_other_repo_000"
    ]
  }
}
```

它在测试：

```text
系统能不能从一句“写启动说明”里主动想起：
- 用户文档偏好
- 当前项目启动命令
- 当前项目验证规则

同时排除其他 repo 的相似启动命令。
```

这就是“说一句话，能想起哪些记忆”的测试。

## 4. 生命周期测试样例

来源：

```text
tests/fixtures/golden_cases/lifecycle.jsonl
```

### 4.1 stale 后不再召回

样本：

```json
{
  "name": "mark_stale_excludes_retrieval_000",
  "category": "mark_stale_excludes_retrieval",
  "memories": [
    {
      "alias": "stale_memory_000",
      "content": "LIFE_STALE_000 start command is npm run dev.",
      "memory_type": "project_fact",
      "scope": "repo:C:/workspace/lifecycle",
      "subject": "start command 000",
      "confidence": "confirmed"
    }
  ],
  "action": {
    "type": "mark_stale",
    "alias": "stale_memory_000",
    "reason": "Source file changed."
  },
  "expected": {
    "statuses": {
      "stale_memory_000": "stale"
    },
    "search_query": "LIFE_STALE_000",
    "search_aliases": [],
    "versions": {
      "stale_memory_000": ["create", "stale"]
    }
  }
}
```

它在测试：

```text
一条旧事实被标记 stale 后，默认检索不能再把它召回。
但它不能直接消失，版本记录里必须留下 create -> stale。
```

期望结果：

```text
status = stale
search_memory 找不到它
memory_versions = create -> stale
```

### 4.2 supersede 用新事实替代旧事实

样本类似：

```json
{
  "category": "supersede_replaces_active",
  "memories": [
    {
      "alias": "supersede_old_000",
      "content": "LIFE_SUPERSEDE_000 start command is npm run dev."
    }
  ],
  "candidates": [
    {
      "alias": "supersede_new_000",
      "content": "LIFE_SUPERSEDE_000 start command is pnpm dev."
    }
  ],
  "action": {
    "type": "supersede",
    "old_alias": "supersede_old_000",
    "candidate_alias": "supersede_new_000"
  },
  "expected": {
    "statuses": {
      "supersede_old_000": "superseded",
      "supersede_new_000": "active"
    },
    "search_aliases": ["supersede_new_000"],
    "versions": {
      "supersede_old_000": ["create", "supersede"],
      "supersede_new_000": ["create"]
    }
  }
}
```

它在测试：

```text
旧启动命令被新启动命令替代后，只能召回新记忆。
旧记忆要保留审计记录，但不能继续污染当前回答。
```

期望结果：

```text
旧记忆 superseded
新记忆 active
搜索只返回新记忆
旧记忆版本链是 create -> supersede
```

## 5. 自动巩固测试样例

来源：

```text
tests/fixtures/golden_cases/consolidation.jsonl
```

### 5.1 多条用户偏好合并为一条 consolidated 记忆

样本：

```json
{
  "name": "merge_user_preference_000",
  "category": "merge_user_preference",
  "memories": [
    {
      "alias": "pref_first_000",
      "content": "CONS_PREF_000 user prefers concise Chinese documentation.",
      "memory_type": "user_preference",
      "scope": "global",
      "subject": "documentation style",
      "confidence": "confirmed"
    },
    {
      "alias": "pref_second_000",
      "content": "CONS_PREF_000 user wants facts separated from inference.",
      "memory_type": "user_preference",
      "scope": "global",
      "subject": "documentation style",
      "confidence": "confirmed"
    }
  ],
  "action": {
    "type": "propose_and_commit",
    "scope": "global",
    "memory_type": "user_preference"
  },
  "expected": {
    "candidate_count": 1,
    "source_aliases": ["pref_first_000", "pref_second_000"],
    "statuses": {
      "pref_first_000": "superseded",
      "pref_second_000": "superseded",
      "consolidated": "active"
    },
    "search_query": "CONS_PREF_000",
    "search_aliases": ["consolidated"]
  }
}
```

它在测试：

```text
两条记忆 scope/type/subject 完全一致，并且都是 confirmed。
系统应该先生成 consolidation candidate。
commit 后只保留新的 consolidated 记忆参与默认检索。
两条来源记忆都变成 superseded。
```

### 5.2 不该巩固的边界

`consolidation.jsonl` 还覆盖三类重要反例：

```text
skip_cross_scope: 相似内容但 scope 不同，不能合并。
skip_different_type: subject 相同但 memory_type 不同，不能合并。
skip_inactive / skip_low_confidence: stale 或 inferred 记忆不参与自动巩固。
```

这一步的价值是避免“越总结越错”。巩固不是简单摘要，而是一次带生命周期影响的写入操作，所以必须先证明来源记忆属于同一个适用范围和同一种记忆类型。

## 6. 图谱召回测试样例

来源：

```text
tests/fixtures/golden_cases/graph_recall.jsonl
```

### 6.1 repo 实体召回启动命令

样本：

```json
{
  "name": "repo_entity_recall_000",
  "category": "repo_entity_recall",
  "task": "GRAPH_REPO_000 这个项目启动失败，帮我排查",
  "scope": "repo:C:/workspace/graph",
  "memories": [
    {
      "alias": "repo_memory_000",
      "content": "GRAPH_REPO_000 start command is pnpm dev.",
      "memory_type": "project_fact",
      "scope": "repo:C:/workspace/graph"
    }
  ],
  "entities": [
    {
      "alias": "repo",
      "name": "repo:C:/workspace/graph",
      "entity_type": "repo",
      "aliases": ["GRAPH_REPO_000"]
    },
    {
      "alias": "command",
      "name": "pnpm dev",
      "entity_type": "command"
    }
  ],
  "relations": [
    {
      "from_alias": "repo",
      "relation_type": "has_start_command",
      "to_alias": "command",
      "source_memory_aliases": ["repo_memory_000"]
    }
  ],
  "expected": {
    "included_aliases": ["repo_memory_000"],
    "excluded_aliases": []
  }
}
```

它在测试：

```text
scope 能匹配当前 repo 实体。
repo -> has_start_command -> command 这条关系能找到来源记忆。
来源记忆是 active，且在当前 scope 内，所以可以进入上下文。
```

### 6.2 图谱召回的反例

`graph_recall.jsonl` 还覆盖这些边界：

```text
cross_scope_exclusion: 其他 repo 的相似实体关系不能串入当前 repo。
old_memory_exclusion: superseded 旧记忆不能被图谱重新召回。
low_confidence_relation_exclusion: inferred 关系不能直接强注入上下文。
```

这组测试的核心不是证明图谱“更聪明”，而是证明图谱不会绕过已有治理规则。图谱只提供关系路径，最终仍要服从 scope、status、confidence 和 context budget。

## 7. 图谱冲突测试样例

来源：

```text
tests/fixtures/golden_cases/graph_conflicts.jsonl
```

### 7.1 同一个 repo 出现两个启动命令

样本：

```json
{
  "name": "start_command_conflict_000",
  "category": "start_command_conflict",
  "memories": [
    {
      "alias": "start_old_000",
      "content": "GRAPH_CONFLICT_START_000 start command is npm run dev."
    },
    {
      "alias": "start_new_000",
      "content": "GRAPH_CONFLICT_START_000 start command is pnpm dev."
    }
  ],
  "entities": [
    {"alias": "repo", "name": "repo:C:/workspace/graph-conflicts"},
    {"alias": "npm", "name": "npm run dev"},
    {"alias": "pnpm", "name": "pnpm dev"}
  ],
  "relations": [
    {
      "from_alias": "repo",
      "relation_type": "has_start_command",
      "to_alias": "npm",
      "source_memory_aliases": ["start_old_000"]
    },
    {
      "from_alias": "repo",
      "relation_type": "has_start_command",
      "to_alias": "pnpm",
      "source_memory_aliases": ["start_new_000"]
    }
  ],
  "expected": {
    "conflict_count": 1
  }
}
```

它在测试：

```text
同一个 from entity。
同一个 relation_type。
两个不同 target。
两个关系都有 active source memory。
所以应该被识别为当前事实冲突。
```

### 7.2 不该报冲突的边界

`graph_conflicts.jsonl` 还覆盖这些反例：

```text
same_target_no_conflict: 多条证据都指向同一个目标，不是冲突。
cross_scope_exclusion: 其他 repo 的冲突不会串入当前 repo。
inactive_source_exclusion: stale/archived/superseded 来源不参与当前冲突。
low_confidence_relation_exclusion: inferred 关系不参与当前冲突。
```

这组测试的价值是把“文本冲突”升级为“属性冲突”：不是看到两句话相似就判断冲突，而是看到同一个实体的同一个属性出现多个当前值，才要求复核。

## 8. 冲突解决测试样例

来源：

```text
tests/fixtures/golden_cases/conflict_reviews.jsonl
```

### 8.1 接受新事实

样本：

```json
{
  "name": "accept_new_resolution_000",
  "category": "accept_new_resolution",
  "action": {
    "type": "create_and_resolve",
    "relation_type": "has_start_command",
    "resolve_action": "accept_new"
  },
  "expected": {
    "review_count": 1,
    "review_status": "resolved",
    "recommended_keep_aliases": ["accept_new_new_000"],
    "statuses": {
      "accept_new_old_000": "superseded",
      "accept_new_new_000": "active"
    },
    "conflicts_after": 0
  }
}
```

它在测试：

```text
系统先生成 conflict review。
review 推荐保留较新的来源记忆。
resolve(action=accept_new) 后，旧记忆 superseded，新记忆 active。
同一个图谱冲突不再出现。
```

### 8.2 其他解决动作

`conflict_reviews.jsonl` 还覆盖：

```text
keep_existing_resolution: 保留已有事实，替换后来的冲突事实。
archive_all_resolution: 两边都过期时全部归档。
ask_user_resolution: 证据不足时转人工确认，不改变记忆状态。
duplicate_pending_review: 已有 pending review 时不重复创建。
same_target_no_review: 同目标重复证据不生成 review。
inactive_or_low_confidence_no_review: inactive 或 inferred 不进入 review。
```

这一步把系统从“发现冲突”推进到“治理冲突”。真正修改长期记忆状态的动作仍然必须显式调用 resolve，不会由检测函数自动执行。

## 9. 为什么要写这些“假事实”

因为测试的目标不是证明：

```text
alpha repo 真的使用 pnpm dev
```

而是证明：

```text
当当前 repo、global、其他 repo 都有相似记忆时，系统不会召回错 scope。
当旧事实 stale/archive/supersede 后，系统不会继续拿它回答。
当上下文预算不够时，系统不会硬塞超长记忆。
```

这些才是记忆系统真正要保证的行为。

## 10. 判断一句话

```text
黄金测试集里的内容是测试用事实，不是真实世界事实。
它们存在的目的，是证明记忆系统的行为可靠。
```
