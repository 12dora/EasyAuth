# 钉钉开放平台用量与配额

钉钉开放平台 REST 按次计费。EasyAuth 用 `easyauth.usage` 计量所有出站钉钉调用、入站
回调 / Stream 事件，以及 EasyAuth 调 Authentik / NetBird / 业务应用的内部调用。配额、
降级和告警只作用于**计费**调用；未计费调用只记账，从不被拒绝。

所有出站钉钉 HTTP 必须经过 `DingTalkApiClient._execute_json_request`；该方法在发出
HTTP 之前调用 `usage.recorder.record_and_check(category)`。未声明类别的新接口无法绕过
计量。Stream 打开连接由 Stream 监督循环调用 `record_and_check("stream_open")` 计数。

## 类别

出站钉钉（指标 `api`，来源 `easyauth`）：

| 类别 | 计费 | 优先级 | 对应接口 |
| --- | --- | --- | --- |
| `token` | 否 | P0 | 新版 `/v1.0/oauth2/accessToken` 换票 |
| `probe` | 否 | P2 | 设置页 oapi `/gettoken` 探针 |
| `notify_send` | 是 | P1 | 工作通知 `asyncsend_v2` |
| `robot_send` | 是 | P1 | 服务号机器人 `batchSend` |
| `notify_reconcile` | 是 | P2 | 工作通知 `getsendprogress` / `getsendresult` |
| `approval` | 是 | P0 | 审批实例创建 / 查询 |
| `stream_open` | 是 | P1 | `POST /v1.0/gateway/connections/open` |

入站：`webhook_callback`（指标 `webhook`）、`stream_event`（指标 `stream`），均计费。
内部调用（指标 `internal`，不计费、无优先级）：Authentik 目录 / 管理 / 其它、NetBird、
业务 Webhook / Hook。Authentik fork 上报的目录拉取与登录调用使用 `ak_*` 类别，由
EasyAuth 每分钟拉取后并入同一套小时桶。

缓存命中的 access token **不**计入。只统计实际准备发出的 HTTP。不确定是否计费的端点
一律记为计费。

## 计数与落库

热路径把计数写在 Django cache（生产为 Redis）：

- 小时计数：`usage:{YYYYMMDDHH utc}:{category}:c` 成功记账，
  `usage:{YYYYMMDDHH utc}:{category}:b` 策略拒绝，TTL 3 天。
- 当日计费运行计数：`usage:day:{YYYYMMDD 本地}:api_billed`，供热路径按日帽即时拦截。

键不存在时先 `add` 再 `incr`。任务 `easyauth.usage.flush_counters` 每 60 秒把当前小时
及前两小时的缓存幂等写入 `UsageBucket`（`count = max(已落库, 缓存)`，Redis 清空不会
把已落库数字改小）。读路径把未刷盘的开放小时与已落库桶按 `max` 合并，避免重复计数。

日 / 月边界按 `TIME_ZONE`（默认 `Asia/Shanghai`）的本地日历切分。

## 配额与超限策略

配额不再使用环境变量硬帽。默认（可在控制台「状态健康 / 用量监控」修改，写入
`UsageSettings.config`）：

| 指标 | 月配额 | 日帽 | 默认超限策略 |
| --- | ---: | ---: | --- |
| `api` | 500000 | 5000 | `degrade`：触限拦截 P2；月用量 ≥ 120% 再拦截 P1；P0 始终放行 |
| `webhook` | 50000 | 无 | 仅告警 |
| `stream` | 无 | 无 | 仅告警（可选 `pause_stream`） |

`api` 另支持 `throttle`（触限后 P1/P2 每小时限 N 次）和 `block_all`（计费调用全拒，
含 P0）。未计费调用从不被拒绝。评估任务 `easyauth.usage.evaluate` 每分钟计算执行状态
并写 `UsageRuntimeState`；热路径 `enforcement.decide` 只读缓存。

超限抛出 `DingTalkCallBudgetExceededError`（`DingTalkApiUnavailableError` 子类），本次
HTTP **不会**发出，也**不会**计入 `count`，只增加 `blocked_count`。

## 缓存故障

计量是观测与熔断，不是授权边界。cache 后端异常时最多每分钟打一条 WARNING，并**放行**
该次调用，避免 Redis 抖动把钉钉集成整条打挂。策略已经拒绝的调用仍会拒绝。

## 依赖健康

`dingtalk` 依赖健康在目录同步结论上叠加当日用量：summary 含 `今日用量 billed/total`
（`total` 为当日 api 计费 + 未计费）。执行状态 `normal` → `healthy`；
`degraded` / `throttled` / `stream_paused` → `warning`；`blocked` → `unhealthy`。
与目录同步状态取 worst-of，不改前端消费的健康条目 schema。

保留：`UsageBucket` 与 `UsageAlertEvent` 各 400 天，由每日
`easyauth.health.data_retention_cleanup` 分批删除。
