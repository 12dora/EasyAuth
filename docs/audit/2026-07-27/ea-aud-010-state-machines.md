# EA-AUD-010 状态机数据库真值表

审计日期：2026-07-27

本文记录本次变更已固化到数据库的状态机真值表。根据并行整改分工，本文件只覆盖
`OutboxEvent`、`PendingApprovalCallback` 和 `DingTalkStreamEvent`；`AccessRequest` 与
通知状态机由其他变更集处理，本文不越权定义其约束。

## 迁移前坏数据规则

新增约束前，迁移会先执行只读扫描。只要发现非法历史行，迁移立即失败并输出坏行数量与主键范围。
迁移不会删除、修补、重绑或填充默认值；坏数据必须走单独、显式、可审计的数据修复流程。

## OutboxEvent

状态字段：`status`

| 状态 | 合法字段形状 |
| --- | --- |
| `pending` | `lease_token=""`，`lease_expires_at IS NULL`，`published_at IS NULL`；`last_error` 可为空或保存上次 broker 发布失败原因 |
| `in_flight` | `lease_token` 非空，`lease_expires_at IS NOT NULL`，`last_error=""`，`published_at IS NULL` |
| `published` | `lease_token=""`，`lease_expires_at IS NULL`，`last_error=""`，`published_at IS NOT NULL` |

数据库约束：

- `outbox_status_supported`
- `outbox_state_truth_shape`

正式可达形状来自 `dispatch_pending_events()`：认领时进入 `in_flight` 并写租约；发布成功进入
`published` 并清租约；发布失败回到 `pending` 并保留错误供重试诊断。

## PendingApprovalCallback

状态字段：`state`；回调结果字段：`status`

| `state` | 合法字段形状 |
| --- | --- |
| `pending` | `instance IS NULL`，`applied_at IS NULL`，`last_error=""` |
| `applied` | `instance IS NOT NULL`，`applied_at IS NOT NULL`，`last_error=""` |
| `conflict` | `applied_at IS NULL`，`last_error` 非空；`instance` 可为空或指向已知审批实例 |

`status` 只允许审批终态：`approved`、`rejected`、`canceled`。

数据库约束：

- `workflows_callback_status_terminal`
- `workflows_callback_state_supported`
- `workflows_callback_state_shape`

正式可达形状来自 `apply_instance_callback()` 与 `_apply_callback_locked()`：未知实例先持久化为
`pending`；匹配实例后成为 `applied`；同一 `process_instance_id` 收到相反终态时成为
`conflict`。冲突状态会清空旧 `applied_at`，避免同时表达“已应用”和“冲突”。

## DingTalkStreamEvent

状态字段：`status`

| 状态 | 合法字段形状 |
| --- | --- |
| `received` | `processed_at IS NULL`，`error=""` |
| `processed` | `processed_at IS NOT NULL`，`error=""` |
| `skipped` | `processed_at IS NOT NULL`，`error=""` |
| `failed` | `processed_at IS NOT NULL`，`error` 非空 |

数据库约束：

- `integrations_stream_status_supported`
- `integrations_stream_state_shape`

正式可达形状来自 `record_stream_event()` 与 `process_dingtalk_stream_event_task()`：Stream 收件先以
`received` 落库；处理成功进入 `processed`；记录但无需消费的事件进入 `skipped`；契约错误或审批
回调冲突进入 `failed` 并保留错误。
