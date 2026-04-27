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

建议建立 `tests/fixtures/golden_cases/`。

```text
golden_cases/
  write_policy.jsonl
  retrieval.jsonl
  conflict.jsonl
  sensitive.jsonl
  context_composition.jsonl
  troubleshooting.jsonl
```

每条 case 包含：

```json
{
  "id": "case_001",
  "name": "一次性请求不写入",
  "events": [
    {
      "event_type": "user_message",
      "content": "帮我把这句话改得更正式一点。",
      "scope": "global"
    }
  ],
  "expected": {
    "candidate_count": 0,
    "decision": "reject",
    "committed": false
  }
}
```

黄金测试集应该手工维护，避免测试也被模型污染。

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

## 10. 推荐验证顺序

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

