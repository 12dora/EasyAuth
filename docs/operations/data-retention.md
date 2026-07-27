# 数据保留与自动清理

## 原则

清理只在业务重试窗口和审计窗口都结束后执行。待处理、可重试或仍需人工处置的数据**不会**被
静默删除。

统一任务是 `easyauth.health.data_retention_cleanup`，默认每天执行一次，每轮每类数据最多处理
500 行。批次上限避免清理变成长事务；积压由下一轮继续处理。

"最小化"指的是保留业务事实的骨架（ID、状态、时间、摘要），只清掉个人信息或原始报文。

## 保留矩阵

| 数据集 | 保留窗口 | 到期动作 | 不处理 |
| --- | ---: | --- | --- |
| 离职 `UserMirror` 画像 | 离职后 30 天 | 清空姓名、邮箱、头像、部门、工号、主管、union id；保留 `authentik_user_id`、状态和钉钉绑定 | 非 `departed` |
| 离职 `DingTalkUserMirror` 画像 | `departed_at` 后 30 天 | 清空姓名、头像、职务、邮箱、手机、工号、部门、主管、union id；保留 source/corp/userid、状态、离职时间、同步代次 | 未离职或未到期 |
| 钉钉 Stream 原文 | 终态后 30 天 | 记录 `data_sha256` 后把 `data` 置空，写 `data_minimized_at`；保留事件 id、类型、corp、状态、结果、错误 | `received` |
| Webhook 投递原文 | 终态后 7 天 | 记录 `payload_sha256` 后把 `payload` 置空，写 `payload_minimized_at`；保留 delivery id、事件类型、目标 URL、状态、尝试次数、generation、错误 | `pending` |
| 依赖健康历史 | `checked_at` 后 30 天 | 分批物理删除历史快照（最新状态由后续探测继续写入） | 未到期 |
| 目录聚合审计桶 | 小时桶闭合后 | 追加为 `AuditLog` 并标记 `flushed_at` | 当前小时桶 |
| 审计日志 | `created_at` 后 365 天 | 分批物理删除 | 未到期 |

通知消息（`NotifyMessage`）由独立的 `easyauth.notify.prune_messages` 按 180 天保留期清理。

## Webhook 重投边界

自动重试窗口约 6 小时，人工排障窗口 7 天。

`pending` 行仍需要原始 payload 重新签名投递，因此**不会**被最小化。`failed` 行超过 7 天后
原文被最小化，此后重投接口返回冲突——要求重新生成业务事件，而不是用空 payload 投递。

## 钉钉 Stream 幂等指纹

`DingTalkStreamEvent` 在创建时就计算 canonical JSON 的 `data_sha256`，不等到清理时才补。

同一 `event_id` 的重投，只有在 `event_type`、`corp_id`、`born_at` 和 `data_sha256` **全部一致**
时才视为 duplicate；原文已最小化后仍能用持久摘要判定。若同一 `event_id` 携带不同业务指纹，
入口记 `dingtalk_stream_event_conflict` 审计并向钉钉返回系统异常，避免 ACK 掉冲突事件。

## 查询计划验证

清理和"最新健康状态"读取必须走有界索引路径。回归测试
`tests/integration/postgres/test_retention_query_plans.py` 在 PostgreSQL lane 上用足量选择性
数据 + `ANALYZE` 后读取自然 planner 的 `EXPLAIN`，**不得**使用 `SET enable_seqscan=off`，也
不得只改断言。

健康页最新状态使用窗口函数按 `dependency` 分区取最新一行（索引 `app_dep_health_latest_idx`），
不在 Python 里遍历整张历史表。
