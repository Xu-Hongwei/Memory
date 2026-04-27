# 03. 数据模型

## 1. 设计目标

数据模型需要同时满足：

- 可检索
- 可解释
- 可验证
- 可修订
- 可审计
- 可迁移

因此建议采用：

```text
Event Log
+ Memory Item
+ Memory Version
+ Memory Relation
+ Retrieval Log
```

## 2. Event Log

用于保存原始事件。

### 2.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 事件 ID |
| `event_type` | string | `user_message`、`tool_result`、`file_observation` 等 |
| `content` | text | 原始内容或摘要 |
| `source` | string | 来源 |
| `created_at` | datetime | 创建时间 |
| `sensitivity` | string | 敏感级别 |
| `metadata` | json | 额外字段 |

### 2.2 示例

```json
{
  "id": "evt_20260427_001",
  "event_type": "user_message",
  "content": "用户要求记忆系统宁可少记，也不要污染记忆。",
  "source": "conversation",
  "created_at": "2026-04-27T10:00:00+08:00",
  "sensitivity": "low",
  "metadata": {
    "conversation_id": "conv_001"
  }
}
```

## 3. Memory Item

用于保存当前生效的长期记忆。

### 3.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 记忆 ID |
| `type` | string | 记忆类型 |
| `scope` | string | 适用范围 |
| `subject` | string | 记忆主题 |
| `content` | text | 记忆正文 |
| `status` | string | `active`、`stale`、`archived`、`rejected` |
| `confidence` | string | `confirmed`、`likely`、`inferred`、`unknown` |
| `source_event_ids` | json | 来源事件 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |
| `last_used_at` | datetime | 最近使用时间 |
| `last_verified_at` | datetime | 最近验证时间 |
| `expires_at` | datetime | 过期时间 |
| `tags` | json | 标签 |
| `metadata` | json | 其他结构化字段 |

### 3.2 类型枚举

```text
user_preference
project_fact
tool_rule
environment_fact
troubleshooting
decision
workflow
reflection
```

### 3.3 范围设计

`scope` 建议采用层级结构：

```text
global
user:{user_id}
workspace:{workspace_id}
repo:{repo_path}
project:{project_id}
agent:{agent_id}
task:{task_id}
```

示例：

```text
global
repo:C:\Users\Administrator\Desktop\memory
project:memory-system
```

### 3.4 置信度

| 值 | 说明 |
| --- | --- |
| `confirmed` | 明确验证过 |
| `likely` | 很可能正确，但证据不完整 |
| `inferred` | 由模型推断，不应强依赖 |
| `unknown` | 未确认 |

长期记忆默认应该尽量只保存 `confirmed` 或高质量 `likely`。

## 4. Memory Version

用于保存记忆的历史版本。

### 4.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 版本 ID |
| `memory_id` | string | 所属记忆 |
| `version` | integer | 版本号 |
| `content` | text | 当时内容 |
| `change_type` | string | `create`、`update`、`merge`、`archive` |
| `change_reason` | text | 变更原因 |
| `source_event_ids` | json | 证据 |
| `created_at` | datetime | 创建时间 |

### 4.2 设计理由

版本表用于避免直接覆盖历史，让系统能够回答：

- 这条记忆什么时候产生的
- 为什么后来被改了
- 新旧记忆有什么区别
- 是否可以回滚

## 5. Memory Relation

用于表达实体和记忆之间的关系。

### 5.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 关系 ID |
| `from_id` | string | 起点 |
| `relation_type` | string | 关系类型 |
| `to_id` | string | 终点 |
| `confidence` | string | 置信度 |
| `source_event_ids` | json | 来源 |

### 5.2 关系类型

```text
belongs_to
uses
depends_on
conflicts_with
supersedes
duplicates
derived_from
blocks
solves
```

## 6. Retrieval Log

用于记录每次记忆检索。

### 6.1 字段设计

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 检索 ID |
| `query` | text | 查询内容 |
| `task_type` | string | 任务类型 |
| `retrieved_memory_ids` | json | 召回结果 |
| `used_memory_ids` | json | 实际注入结果 |
| `created_at` | datetime | 时间 |
| `metadata` | json | 排名分数等 |

### 6.2 作用

Retrieval Log 可以帮助优化：

- 哪些记忆经常被用到
- 哪些记忆从不被用到
- 哪些记忆检索相关但没有被采纳
- 哪些任务检索策略需要调整

## 7. 排错经验结构

排错经验建议强制使用固定结构：

```text
问题：
经验：
解决方式：
证据：
适用范围：
```

示例：

```json
{
  "type": "troubleshooting",
  "scope": "repo:C:\\Users\\Administrator\\Desktop\\example",
  "subject": "Windows PowerShell 中文乱码",
  "content": {
    "问题": "在 PowerShell 中运行脚本后中文输出乱码。",
    "经验": "终端编码正常时，下一步应检查文件本身编码，而不是重复调整终端。",
    "解决方式": "先检查 chcp 和 PowerShell 编码，再用文件级读取确认源文件编码。",
    "证据": "已通过命令检查确认 code page 为 65001。",
    "适用范围": "Windows PowerShell 项目脚本调试"
  },
  "confidence": "confirmed"
}
```

