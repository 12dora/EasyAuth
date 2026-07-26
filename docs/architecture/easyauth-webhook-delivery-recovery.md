# EasyAuth Webhook 投递恢复协议

## 目标

本文记录 `EA-AUD-004` 的整改后事实：Webhook 投递一旦被 worker 认领，系统必须能从非预期异常、
软超时、硬超时或 worker 丢失中恢复。恢复必须产生可审计的新尝试，不能把认领字段静默清空，也
不能把未完成投递返回为成功。

## 状态真值

`WebhookDelivery` 只有三个持久状态：

| 状态 | 含义 | 允许的租约形状 |
| --- | --- | --- |
| `pending` | 等待投递、正在投递或等待恢复 | 未认领时 `claim_token=""` 且 `lease_expires_at=null`；认领后两者必须同时存在 |
| `delivered` | 目标端返回 `2xx`，当前 `generation` 的认领令牌已完成写回 | `claim_token=""` 且 `lease_expires_at=null` |
| `failed` | 重试耗尽或配置缺失，必须由人工判断后重投 | `claim_token=""` 且 `lease_expires_at=null` |

`generation` 是投递行的防护代次。人工重投和 watchdog 恢复都会推进 `generation`，旧 worker
只能携带旧代次和旧令牌写回；这类写回会被条件更新拒绝。

## 自动恢复

worker 认领投递时会写入唯一 `claim_token`、当前 `generation` 和租约到期时间。若 worker 在
认领后遇到已归一化传输失败或非预期异常，任务会把错误写入 `last_error`，清除当前租约，并按
重试计划写入下一次 outbox 任务。

若 worker 被硬超时终止或进程丢失，代码无法在原进程内执行清理。Celery beat 会周期性运行
`easyauth.webhooks.recover_expired_leases`，扫描 `pending` 且租约过期的投递，执行以下原子动作：

1. 推进 `generation`；
2. 清除旧 `claim_token` 和旧租约到期时间；
3. 写入类型化恢复错误；
4. 使用 `delivery_id + generation` 写入新的幂等 outbox 任务；
5. 记录 `webhook_delivery_recovery_scheduled` 审计事件。

这不是把投递重置为空状态，而是明确声明旧认领已经失效，并创建下一次可审计尝试。

## 人工恢复边界

控制台人工重投只接受 `failed`。`pending` 的恢复权威属于 watchdog，因为 `pending` 可能仍有活跃
worker；人工把它直接重投会绕过租约和代次防护。

人工重投会把状态从 `failed` 改为 `pending`，重置尝试次数和错误，推进 `generation`，然后写入
新的 outbox 任务。同一失败行的并发人工重投只有一个能成功。

## 审计与告警

投递成功记录 `webhook_delivered`，重试耗尽记录 `webhook_delivery_exhausted`，过期租约恢复记录
`webhook_delivery_recovery_scheduled`，人工重投记录 `webhook_delivery_redelivered`。运维侧可
按这些事件与 `last_error` 追踪恢复原因、尝试次数和对应应用。
