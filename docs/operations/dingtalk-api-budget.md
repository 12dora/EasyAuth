# 钉钉开放平台日调用预算

钉钉开放平台 REST 按次计费。所有付费调用必须经过
`DingTalkApiClient._execute_json_request`；该方法在发出 HTTP 之前调用
`record_and_check(category)` 记账并检查日预算。未声明类别的新接口无法绕过计量。

## 类别

| 类别 | 对应接口 |
| --- | --- |
| `token` | 新版 `/v1.0/oauth2/accessToken` 换票 |
| `notify_send` | 工作通知 `asyncsend_v2` |
| `notify_reconcile` | 工作通知 `getsendprogress` / `getsendresult`（唯一轮询类别） |
| `robot_send` | 服务号机器人 `batchSend` |
| `approval` | 审批实例创建 / 查询 |
| `probe` | 设置页 oapi `/gettoken` 探针 |

缓存命中的 access token **不**计入。只统计实际准备发出的 HTTP。

## 预算

按 `TIME_ZONE`（默认 `Asia/Shanghai`）的本地日历日切分，计数写在共享 Django cache
（生产为 Redis）里，键 TTL 3 天。

| 环境变量 | 默认 | 含义 |
| --- | ---: | --- |
| `EASYAUTH_DINGTALK_DAILY_CALL_BUDGET` | 5000 | 全部类别的日硬帽 |
| `EASYAUTH_DINGTALK_DAILY_RECONCILE_CALL_BUDGET` | 1000 | 仅 `notify_reconcile` 的日子帽 |

启动时校验必须为大于 0 的整数。硬帽耗尽后**所有**类别都被拒绝；对账子帽耗尽时
`notify_send` 等其它类别仍可调用。超帽抛出 `DingTalkCallBudgetExceededError`
（`DingTalkApiUnavailableError` 子类），本次 HTTP **不会**发出，也**不会**计入。
每个 `(日, 类别)` 第一次触帽打一条 ERROR，之后拒绝不再重复打日志。

## 缓存故障

计量是观测与熔断，不是授权边界。cache 后端异常时记 WARNING 并**放行**该次调用，
避免 Redis 抖动把钉钉集成整条打挂。

## 依赖健康

`dingtalk` 依赖健康在目录同步结论上叠加当日用量：summary 含 `今日调用 total/硬帽`
与各类别计数。总量达到硬帽 80%，或对账子帽耗尽 → `warning`；硬帽耗尽 → `unhealthy`。
与目录同步状态取 worst-of，不改前端消费的健康条目 schema。
