# 异步安全动作状态机

本文记录离职禁号与连接器对账的共同运行口径。两者都属于安全敏感异步动作：任务返回成功必须表示动作已经完成，或已经进入可恢复的权威排队状态；不得把未配置、查找失败、分页上限、失租或外部依赖失败解释为成功。

## 离职禁号

入口是 `disable_departed_account_task`，目标是把 `UserMirror.authentik_user_id` 对应的 Authentik 用户禁用并吊销会话。

状态口径：

| 状态 | 含义 | 后续动作 |
| --- | --- | --- |
| `queued` | `lifecycle-disable-account:{task.id}` 已写入事务发件箱 | worker 领取任务 |
| `running` | worker 正在调用 Authentik 管理 API | 成功或抛出类型化失败 |
| `disabled` | 用户已禁用，会话吊销已完成 | 记录 `lifecycle_account_disabled` 审计 |
| `failed_retryable` | 管理 API 未配置、分页超过上限、用户查找失败、网络或契约错误 | 记录 `lifecycle_account_disable_failed` 审计并抛出，由 Celery 重试或进入失败队列 |

规则：

- `AuthentikAdminNotConfiguredError` 是部署缺陷，不返回 `not_configured` 成功字符串。
- `AuthentikAdminUserNotFoundError` 表示安全动作未完成，不返回 `user_not_found` 成功字符串。
- 分页未到真实末页但超过 `_MAX_USER_PAGES` 时抛 `AuthentikAdminPaginationLimitError`，不得伪装成用户不存在。
- 每次失败审计只记录类型化 `detail`，不记录 token、响应正文或其他敏感明文。

## 连接器对账

连接器实例以 `ConnectorInstance` 为聚合根。`reconcile_generation` 是待收敛事实代次，`reconciled_generation` 是已经完成的代次，`reconcile_lease_token` 与 `reconcile_lease_expires_at` 是当前 worker 的唯一租约。

状态口径：

| 状态 | 判定 | 含义 |
| --- | --- | --- |
| `idle` | 无 dirty、无 queued、无有效租约 | 外部系统已收敛到当前代次或没有待执行工作 |
| `queued` | `reconcile_worker_queued=True` 且无有效租约 | 已有 worker 投递等待领取 |
| `running` | `reconcile_lease_token` 与未过期 `reconcile_lease_expires_at` 同时存在 | 某个 worker 持有当前代次租约 |
| `dirty` | `reconcile_dirty=True` 且无有效租约 | 有新代次等待重新入队或接管 |

数据库不变量：

- `reconciled_generation <= reconcile_generation`。
- `reconcile_lease_token` 与 `reconcile_lease_expires_at` 必须同时为空或同时非空。
- `reconcile_pending_trigger` 只允许 `periodic`、`event`、`manual`、`offboard`。

租约和任务时限：

- `RECONCILE_TASK_TIME_LIMIT_SECONDS`、`RECONCILE_TASK_SOFT_TIME_LIMIT_SECONDS`、`RECONCILE_LEASE_SECONDS`、`RECONCILE_QUEUE_CLAIM_TIMEOUT_SECONDS` 来自同一配置源。
- 租约长度为 hard time limit 加固定缓冲，确保旧 worker 在硬时限内不能失租后继续写外部系统。
- 调度器只有在无有效租约且队列标记过期时才重新投递。

外部写入 fencing：

所有外部写入前必须调用 `external_write_allowed(instance, user_id=..., require_active_user=...)` 续租并比较：

- `ConnectorInstance.id` 相同；
- `reconcile_generation` 仍等于 worker 领取时的 generation；
- `reconcile_dirty=False`；
- `reconcile_lease_token` 仍等于 worker 领取时的 token；
- `reconcile_lease_expires_at` 仍未过期。

该规则覆盖创建用户、加组、解封、撤组、封禁和离职快路径。扩权与解封额外要求 `UserMirror.status == active`；撤组与封禁只要求本地仍存在该用户镜像，因为离职用户仍需要收缩外部权限。

worker 失去租约或发现 dirty 后必须立即停止外部写入，返回 `failed` 运行结果并包含 `users_fenced`，不得继续处理后续用户、不得把本轮解释为成功。`_finish_generation()` 只有在 token、generation 与未过期租约同时匹配时才允许把本 generation 记为完成；如果 token 仍归本 worker 且租约未过期，但 generation 已被新事件推进，只能释放本 worker 租约、保留 `dirty`，不得推进 `reconciled_generation`。失败运行不推进 `reconciled_generation`，只把实例标回 `dirty` 等待后续重试。`_finish_generation()` 拒绝旧 token 只是数据库释放保护，不能作为外部副作用的唯一 fence。

## 运维 API

控制台连接器实例响应包含 `reconcile_state`：

- `status`：`idle`、`queued`、`running` 或 `dirty`；
- `generation` 与 `reconciled_generation`；
- `dirty`、`pending_trigger`、`worker_queued`、`worker_queued_at`；
- `lease_active` 与 `lease_expires_at`。

响应不暴露 `reconcile_lease_token`。人工重试只能通过 `POST /console/api/v1/apps/{app_key}/connectors/{instance_id}/reconcile` 推进新 generation 并入队，不能直接清租约、改代次或把失败标记为成功。
