# 异步动作与失败语义

本文是后端"什么算成功、什么必须失败"的统一口径，覆盖同步接口、Celery 任务、连接器对账和
Webhook 投递。

## 一条总规则

**没有真正做完的事，不能返回成功。**

缺少上游事实、缺少本地前置条件、依赖不可用、部分失败——全部必须显式失败并保留可诊断信息，
不得用空结果、旧数据、默认值或"已接收"伪装成完成。

## 同步接口的失败边界

| 场景 | 行为 |
| --- | --- |
| OIDC 回调时本地用户不是 `active` | `403`，只清理 OIDC 尝试态，不写登录会话 |
| 给已停用应用签发/轮换静态 token | `409`，不生成 secret，不写凭据 |
| 紧急撤权时该用户在该应用没有当前有效授权 | `409`，不记成功审计 |
| 审批通过但授权落地失败 | `422`，响应同时说明"审批决策已提交"并返回最新审批快照 |
| 托管用户预览遇目录错误或快照过期 | `503`，不返回空列表 |
| 钉钉通知回执字段缺失或类型错误 | 只记该收件人 `error`，不推进 `last_reconciled_at` |

## 离职禁号任务

入口 `disable_departed_account_task`，把 `UserMirror.authentik_user_id` 对应的 Authentik
用户禁用并吊销会话。

| 状态 | 含义 |
| --- | --- |
| `queued` | `lifecycle-disable-account:{task.id}` 已写入事务发件箱 |
| `running` | worker 正在调用 Authentik 管理 API |
| `disabled` | 已禁用并吊销会话，记 `lifecycle_account_disabled` 审计 |
| `failed_retryable` | 管理 API 未配置、分页超上限、用户查找失败、网络或契约错误 |

未配置、用户查不到、分页超过 `_MAX_USER_PAGES` 都抛类型化异常走 Celery 重试，**不返回
`not_configured` / `user_not_found` 这类"成功字符串"**。失败审计只记类型化 `detail`，
不记 token 或响应正文。

## 连接器对账

聚合根是 `ConnectorInstance`。`reconcile_generation` 是待收敛的事实代次，
`reconciled_generation` 是已完成代次，`reconcile_lease_token` + `reconcile_lease_expires_at`
是当前 worker 的唯一租约。

| 状态 | 判定 |
| --- | --- |
| `idle` | 无 dirty、无 queued、无有效租约 |
| `queued` | 已投递等待领取，且无有效租约 |
| `running` | 租约 token 与未过期到期时间同时存在 |
| `dirty` | 有新代次待重新入队或接管 |

数据库不变量：`reconciled_generation <= reconcile_generation`；租约 token 与到期时间必须同
空或同非空；`reconcile_pending_trigger` 只能是 `periodic` / `event` / `manual` / `offboard`。

**租约必须长于任务硬时限**（hard time limit + 固定缓冲），否则旧 worker 可能在失租之后继续
写外部系统。相关时限取自同一配置源：`RECONCILE_TASK_TIME_LIMIT_SECONDS`、
`RECONCILE_TASK_SOFT_TIME_LIMIT_SECONDS`、`RECONCILE_LEASE_SECONDS`、
`RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS`。

### 外部写入前的 fencing

每次外部写入前调用 `external_write_allowed(instance, user_id=..., require_active_user=...)`
续租并校验：实例 ID、generation 未变、`reconcile_dirty=False`、租约 token 未变、租约未过期。
覆盖创建用户、加组、解封、撤组、封禁和离职快路径。

- 扩权与解封额外要求 `UserMirror.status == active`。
- 撤组与封禁只要求本地仍有该用户镜像——**离职用户仍然需要收缩外部权限**。

worker 一旦失租或发现 dirty，必须立即停止外部写入，返回 `failed` 并带 `users_fenced`，不继续
处理后续用户，也不把本轮当成功。`_finish_generation()` 只在 token、generation 和未过期租约
同时匹配时才推进 `reconciled_generation`；若 token 仍属本 worker 但 generation 已被新事件推
进，只释放租约并保留 `dirty`。

### 运维 API

控制台连接器实例响应包含 `reconcile_state`：`status`、`generation`、`reconciled_generation`、
`dirty`、`pending_trigger`、`worker_queued`、`worker_queued_at`、`lease_active`、
`lease_expires_at`；**不暴露** `reconcile_lease_token`。

人工重试只能通过
`POST /console/api/v1/apps/{app_key}/connectors/{instance_id}/reconcile` 推进新 generation
并入队，不能直接清租约、改代次或把失败标为成功。

## Webhook 投递恢复

`WebhookDelivery` 只有三个持久状态：

| 状态 | 含义 | 租约形状 |
| --- | --- | --- |
| `pending` | 等待投递、正在投递或等待恢复 | 未认领时两个字段都空；认领后必须同时存在 |
| `delivered` | 目标端返回 `2xx` | 两个字段都空 |
| `failed` | 重试耗尽或配置缺失，需人工判断 | 两个字段都空 |

`generation` 是防护代次：人工重投和 watchdog 恢复都会推进它，旧 worker 携带旧代次的写回会被
条件更新拒绝。

**自动恢复**：worker 认领时写入唯一 `claim_token`、当前 `generation` 和租约到期时间。进程内
可捕获的失败会写 `last_error`、清租约并按重试计划重新入队。进程被硬超时杀掉或丢失时，
Celery beat 周期运行 `easyauth.webhooks.recover_expired_leases`，对租约过期的 `pending` 行
原子地：推进 `generation` → 清旧租约 → 写类型化恢复错误 → 用 `delivery_id + generation`
写幂等 outbox 任务 → 记 `webhook_delivery_recovery_scheduled` 审计。

**人工重投只接受 `failed`。** `pending` 的恢复权威属于 watchdog，因为它可能仍有活跃 worker；
人工直接重投会绕过租约和代次防护。同一失败行的并发重投只有一个能成功。

审计事件：`webhook_delivered`、`webhook_delivery_exhausted`、
`webhook_delivery_recovery_scheduled`、`webhook_delivery_redelivered`。
