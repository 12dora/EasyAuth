# 平台能力升级设计：公共用户目录 API + 统一钉钉通知 API

状态：已实施，按第 9 篇偏差记录收敛 ｜ 日期：2026-07-16 ｜ 首个消费方：EasyProject（app_key=easyproject）

## 文档索引

| 篇 | 文件 | 内容 |
|---|---|---|
| 1 | [01-API契约-权威版.md](01-API契约-权威版.md) | **下游实现的唯一依据**：7 个端点全量契约 + 与草案差异对照表（14 项） |
| 2 | [02-数据模型改动.md](02-数据模型改动.md) | `AppCapability` / `NotifyMessage` / `NotifyRecipient` 字段级定义、accounts 索引、迁移清单 |
| 3 | [03-Celery任务与投递管道.md](03-Celery任务与投递管道.md) | 复用 outbox、参照 webhooks 骨架新建管道的论证；三任务划分、重试/幂等/死信 |
| 4 | [04-钉钉工作通知调研结论.md](04-钉钉工作通知调研结论.md) | asyncsend_v2 规格、官方频控数字（全部带出处）、凭据结论 |
| 5 | [05-安全设计.md](05-安全设计.md) | 字段最小化裁决表、通知范围权衡、限流矩阵、审计点 |
| 6 | [06-SDK接口设计.md](06-SDK接口设计.md) | directory / notify 方法、0.3.0 结构化错误、manifest `capabilities` 节 |
| 7 | [07-实施与发布计划.md](07-实施与发布计划.md) | 模块归属、5 个 PR 切分、灰度/回滚、测试要点 |
| 8 | [08-实施执行顺序-给实施agent.md](08-实施执行顺序-给实施agent.md) | 逐 PR 任务卡（绝对路径级）：读什么/建什么/改什么/测什么、依赖与合入顺序、本机测试环境 |

## 十条核心决策（速览）

1. **路径偏离草案**：`/api/v1/apps/{app_key}/directory/*` 与 `.../notify/*`——沿用
   现有公共 API「路径 app_key 必须等于凭据 app_key」的鉴权不变量；
2. **`user_id` = `authentik_user_id`**（与权限 API 一致），但全量目录含未登录员工
   → `user_id` 可空、`dingtalk_user_id` 恒存在、全契约统一接受 `dt:` 前缀引用；
3. **两能力默认关闭**：超管开通 App capability，App owner 再授予单个
   credential，两层必须同时通过；manifest 顶层 `capabilities` 只表示请求，
   **声明 ≠ App 开通 ≠ 凭据授权**；
4. **目录可安全收敛**：返回 email/mobile/employee_number/status/active，消失员工
   保留 tombstone；多企业 `directory_snapshot` 暴露 generation/快照时间/stale/
   complete/authoritative，列表支持 `snapshot_id` 固定分页；
5. **通知目标 = 任意 active 目录用户**（不限 AccessGrant 持有者——否则击穿
   「通知负责人主管」与「@未开通同事」场景），爆炸半径靠配额+审计+限流控制；
6. **通知管道**：新建 `easyauth.notify` app，复用 outbox 入队，照抄 webhooks 的
   claim/lease/attempts/死信骨架；webhooks transport 不可插拔，不改造；
7. **钉钉侧走旧版 asyncsend_v2**（官方无新版替代）；每个 App 在自己的
   workspace 配置独立、版本化通知通道（app_key/app_secret/agent_id），
   消息受理时冻结通道版本，不复用全局通知身份；
8. **批 100 人/次**（官方 userid_list 上限）；`202` 仅表示已受理，
   `sent` 是最低可靠保证；`delivered` 只来自明确 read/unread 回执，
   不表示已读或合规送达；无明确名单时保持 `sent`，不做 24h 乐观收敛；
9. **`dedup_key` 永久幂等**（DB 唯一约束 + payload_hash 冲突 409），对齐审批
   biz_key 语义；钉钉「相同内容同人一天 1 次」的服务端去重兜底崩溃重发；
10. **SDK 零依赖不变**，当前版本 0.3.0，结构化暴露 error code/details/
    Retry-After 与 retryable，SDK 本身不自动重试。

## 与既有体系的衔接（文件级）

认证 `api/permission_query_auth.py`（复用）· 错误 `api/errors.py`（零新增码）·
分页 `api/pagination.py` · 限流 `config/rate_limit.py` · 审计 `audit/services.py` ·
入队 `outbox/services.py:enqueue_task` · 钉钉 client
`integrations/dingtalk/api_client.py`（追加 3 方法）· 目录数据
`accounts/models.py` 目录镜像表（增加联系字段、tombstone 和 generation）。
