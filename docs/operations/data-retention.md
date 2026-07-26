# 数据保留与自动清理

## 目标

本页定义 `EA-AUD-012`、`EA-AUD-025`、`EA-AUD-026` 相关数据集的最小保留矩阵。清理任务只在
业务重试或审计窗口结束后执行；待处理、可重试或仍需人工处置的数据不会被静默删除。

统一任务为 `easyauth.health.data_retention_cleanup`，默认每天执行一次，每轮每类数据最多处理
500 行。批次上限避免清理任务变成长事务；积压时由下一轮继续处理。

## 保留矩阵

| 数据集 | 保留窗口 | 到期动作 | 保留字段 | 不处理状态 |
| --- | ---: | --- | --- | --- |
| 离职 `UserMirror` 画像 | 离职状态更新后 30 天 | 清空姓名、邮箱、头像、部门、员工号、主管和钉钉 union id | `authentik_user_id`、状态、钉钉 source/corp/userid 绑定、创建/更新时间 | 非 `departed` 用户 |
| 离职 `DingTalkUserMirror` 画像 | `departed_at` 后 30 天 | 清空姓名、头像、职务、邮箱、手机号、员工号、部门列表、主管和 union id | source/corp/userid、状态、离职时间、同步代次 | 未离职或没有到期的用户 |
| DingTalk Stream 原文 | 终态 `processed/skipped/failed` 后 30 天 | 计算 `data_sha256` 后把 `data` 置为空对象，并记录 `data_minimized_at` | event id、类型、corp、状态、结果、错误、处理时间、原文摘要 | `received` |
| Webhook 投递原文 | 终态 `delivered/failed` 后 7 天 | 计算 `payload_sha256` 后把 `payload` 置为空对象，并记录 `payload_minimized_at` | delivery id、事件类型、目标 URL、状态、尝试次数、generation、错误、原文摘要 | `pending` |
| 依赖健康历史 | `checked_at` 后 30 天 | 分批物理删除历史快照 | 每个依赖最新状态由后续探测继续写入 | 未到期快照 |
| 目录聚合审计桶 | 小时桶闭合后 | 分批追加为 `AuditLog` 并标记 `flushed_at` | app、endpoint、小时、调用数、最近结果数、凭据 id | 当前小时桶 |
| 审计日志 | `created_at` 后 365 天 | 通过 `AuditLogQuerySet.purge_created_before()` 分批物理删除 | 窗口内 append-only 审计事实 | 未到期日志 |

## Webhook 重投边界

Webhook 的自动重试最长约 6 小时，人工排障窗口设为 7 天。`pending` 行仍依赖原始 payload
重新签名和投递，因此不会被最小化。`failed` 行超过 7 天后原文会被最小化；此后重投接口返回
冲突错误，要求重新生成业务事件，而不是用空 payload 投递。

## PostgreSQL 证据

PostgreSQL lane 应执行以下查询计划检查，确认清理和最新健康读取走有界索引路径。测试文件
`tests/integration/postgres/test_retention_query_plans.py` 使用足量选择性数据和 `ANALYZE` 后读取
自然 planner 的 `EXPLAIN`，不得使用 `SET enable_seqscan=off`，也不得只改断言。

```sql
EXPLAIN SELECT id
FROM audit_auditlog
WHERE created_at < TIMESTAMPTZ '2000-01-01'
ORDER BY created_at ASC, id ASC
LIMIT 500;

EXPLAIN SELECT id
FROM applications_dependencyhealthsnapshot
WHERE checked_at < TIMESTAMPTZ '2000-01-01'
ORDER BY checked_at ASC, id ASC
LIMIT 500;

EXPLAIN SELECT id
FROM integrations_dingtalkstreamevent
WHERE status = 'processed'
  AND data_minimized_at IS NULL
  AND processed_at < TIMESTAMPTZ '2000-01-01'
ORDER BY processed_at ASC, id ASC
LIMIT 500;

EXPLAIN SELECT id
FROM webhooks_webhookdelivery
WHERE status = 'failed'
  AND payload_minimized_at IS NULL
  AND updated_at < TIMESTAMPTZ '2000-01-01'
ORDER BY updated_at ASC, id ASC
LIMIT 500;
```

健康页最新状态读取使用数据库窗口函数按 `dependency` 分区取最新一行，不再在 Python 中遍历
整张历史表。对应索引是 `app_dep_health_latest_idx`。

## EA-AUD-025 性能归属

| 分类 | 当前处置 | 证据 |
| --- | --- | --- |
| 无界集合 | 不再对 `direct_grants` 设置无产品依据的任意数量上限；保留完整资源选择，scope 校验批量查询，链接落库使用 `bulk_create`。 | `direct_grant_target_errors()`、`_create_direct_grant_links()`、51 项 direct permissions 回归 |
| N+1 | App 列表 readiness 按页批量计算；授权组目录 API 返回标准 `pagination` 信封，只序列化当前页并预取 grant、App 与 managed policy 映射；Matrix 需要全目录时按 `page/page_size` 逐页读取，缺少分页信封或超过前端页数上限时快速失败；岗位模板列表预取当前修订及 items；团队列表分页并只查当前页成员。 | `configuration_readiness_statuses_for_apps()`、`authorization_groups_page_payload()`、`fetchAllAuthorizationGroups()`、`lifecycle_onboarding_templates()`、`console_teams()` |
| 全表扫描 | 健康最新状态改为数据库窗口函数每依赖取 1 行；审计/健康清理按索引批次扫描。 | `DependencyHealthService.latest_items()`、保留索引 |
| 逐行锁 | 审批列表不再逐行调用 `recover_stale_submission()`；本页过期 `submitting` 记录用条件批量更新标为 ambiguous。 | `recover_stale_submissions()` |
| 积压任务 | 过期授权清理按固定批次处理，并在支持的 PostgreSQL 上使用 `select_for_update(skip_locked=True)` 避免重叠 worker 抢同一批。 | `cleanup_expired_grants(batch_size=...)` |
| 非原子指标 | 目录聚合审计改为数据库唯一小时桶和原子 `F(call_count)+1` 更新；闭合桶由清理任务分批 flush 为 append-only `AuditLog`。 | `DirectoryAuditBucket`、`record_directory_audit_bucket()`、`flush_directory_audit_buckets()` |
| 同步远端读取 | 连接器外部组 GET 只读本地 `ConnectorExternalGroup` 快照并分页；POST 显式排队刷新。刷新任务按 connector 分页协议逐页读取远端、按页 `bulk_create(update_conflicts=True)` upsert，最后用本轮 `last_seen_at` 批量失活旧快照，并在实例上记录 `external_groups_refresh_status/cursor/refreshed_at`。NetBird 以 `page/page_size` 拉取组列表；若上游连续满页超过硬上限或跨页重复 ID，刷新明确失败。 | `ConnectorExternalGroup`、`refresh_connector_external_groups_task()`、`iter_external_group_pages()`、`NetBirdClient.iter_group_pages()`、`console_app_connector_external_groups()` |
| 审计/健康增长 | 审计索引、健康索引、自动分批清理和 PostgreSQL 计划测试已补齐。 | 迁移与 `data_retention_cleanup` |

## DingTalk Stream 幂等指纹

`DingTalkStreamEvent` 创建时即计算 canonical JSON `data_sha256`，不再等到保留期清理时才补摘要。同一
`event_id` 的重投只有在 `event_type`、`corp_id`、`born_at` 与 `data_sha256` 全部一致时才视为
duplicate；原文 `data` 已最小化为空对象后，仍用持久摘要判定相同重投。若同一 `event_id` 携带不同业务
指纹，入口记录 `dingtalk_stream_event_conflict` 审计并向钉钉返回系统异常，避免 ACK 掉冲突事件。
