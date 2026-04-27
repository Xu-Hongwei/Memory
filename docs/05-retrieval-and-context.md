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

## 5. 上下文组装

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

## 6. 使用记忆时的回答原则

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

## 7. 检索失败处理

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

## 8. 记忆预算

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

