# 平台能力：企业目录与钉钉通知

除了权限查询，EasyAuth 还向下游应用开放两项平台能力：

- **`directory`** —— 查询企业员工与部门（选人器、找主管、找下属）。
- **`notify`** —— 发送钉钉工作通知。

接口契约见 [公共 API](../api/easyauth-public-api.md) 第 5、6 节。本文只记录接口文档不会重复
的设计口径：能力如何授权、目录引用为什么是 opaque、通知投递能保证什么、钉钉平台有哪些硬
限制。

---

## 1. 能力默认关闭，两层授权

拿到一条 app token **不等于**能拉目录或发通知。必须同时满足两层：

1. **超管**为该 App 开通 `AppCapability`；
2. **App owner** 把 `directory` / `notify` 授予具体的静态 token 或 OAuth 凭据。

任一层缺失返回 `403 PERMISSION_DENIED`（与"凭据无效 `401`"严格区分，避免下游误判成 token
问题）。两类开关动作都写审计。

manifest 顶层 `capabilities: ["directory", "notify"]` 只表达应用的需求，供控制台展示——
**声明 ≠ App 开通 ≠ 凭据授权**，导入不会翻转任何开关。

**下游必须拆成三条凭据**：权限查询凭据不授予任何平台能力，目录凭据只给 `directory`，通知凭
据只给 `notify`，并用三个独立的 `EasyAuthAppClient` 实例。这样常规高频查询 token 泄漏时不会
连带暴露员工枚举和通知发送能力。

## 2. 目录引用是 opaque scoped ref

用户和部门条目返回 `source_slug`、`corp_id` 以及 `user_ref` / `department_ref`。ref 本身已经
包含目录源和企业作用域。

下游必须**原样保存、原样回传**，用于详情、主管、下属、通知和过滤；不得自行拼接、解析，也
不得从 `dingtalk_user_id` / `department_id` 重建。未作用域的裸 ID 会被拒绝
（`failed(USER_NOT_FOUND)`）。

这么做是为了让多企业（多个 corp）共存时原始 ID 不会互相碰撞。

### 字段暴露口径

暴露：`user_id`（可空）、`dingtalk_user_id`、`name`、`avatar_url`、`title`、`departments`、
`email`、`mobile`、`employee_number`、`status`、`active`、`source_slug`、`corp_id`、以及列表/
详情条目上的直接主管摘要（`manager`；无主管或主管镜像不存在时为 `null`）。`/manager`
端点仍返回完整 D1 条目（含该主管自己的 `manager` 摘要）。

不暴露：

- `dingtalk_union_id` —— 跨应用身份标识，泄露面大于价值。
- **完整主管链** —— 业务场景只需要直接主管；整链等于组织结构测绘。

`email` / `mobile` / `employee_number` 属敏感联系信息：不进日志，不作为认证或授权身份键，
下游只能在已批准的业务范围内使用。部门树同样是组织情报，departments 端点一样受 `directory`
开关约束。

### 目录新鲜度

镜像同步目标周期 300 秒，故障时可能滞后更久。beat 每次成功从上游取回权威快照后，即使
generation 未变也会刷新本地 `last_synced_at`——新鲜度表示「已在该时刻核对镜像」，不是
「上游上次发生变化的时间」。下游必须用响应里的
`directory_snapshot.authoritative` / `stale` / `complete` 判断可信性，**不能靠调度周期推断**。
`snapshots[]` 每个 `(source_slug, corp_id)` 作用域一项，不是每个 `corp_id` 一项。

## 3. 通知：能发给谁

**结论：可以通知任意 `active` 目录用户，不限于持有该应用授权的人。**

原因是两个真实场景会被"仅限授权用户"直接击穿：逾期升级要通知负责人的主管（主管很可能没有
该应用的权限）；@提及尚未开通该应用的同事（通知恰恰是引导对方来开通的入口）。而且那样会把
通知能力和授权数据耦合起来——授权一撤销连告别通知都发不出去。

代价是被攻陷的应用可以骚扰全员，因此靠纵深防御而不是范围限制来控制：

1. 能力默认关闭，能发通知的应用是管理员逐个授信的；
2. 每应用双层限流 + 每日收件人配额，把爆炸半径限制在配额内；
3. 全量审计——谁、什么时候、给谁、发了什么类别，可追溯；
4. 内容治理：title / content 长度上限，`deeplink_url` 必须 https（防止钉钉卡片变成钓鱼跳板）；
   发送侧会去掉 markdown 标记，钉钉 OA 正文为纯文本。
5. `active` 硬约束：disabled / departed 一律拒发（`USER_INACTIVE`）；
6. **下游后端必须按业务规则计算收件人**，不得提供"前端传任意 `userRef` 就调用
   `send_notification`"的透传接口。

## 4. 通知通道与投递保证

每个 App 在自己的 workspace 配置**独立、版本化**的钉钉通知通道，绑定目录作用域
（`directory_source_slug` / `corp_id`）。**工作通知发送与回执**不再使用通道上的钉钉应用
凭证，而是走公司级「服务号」：`IntegrationSettings` 的
`dingtalk_notify_app_key` / `dingtalk_notify_app_secret` / `dingtalk_notify_agent_id`。
仅当这三项均非空时使用该三元组换票与 `agent_id`；任一留空则回退到主应用三元组
（目录同步 / Stream / 登录用的 `dingtalk_app_*`）。notify-worker 投递与对账与此同一口径。

工作通知发出后，**同一条消息还会经服务号机器人再发一条一对一消息**（`robotCode` = 服务号
AppKey，权限点 `qyapi_robot_sendmsg`，EasyAuth 只发不收）。走新版
`POST /v1.0/robot/oToMessages/batchSend`（`x-acs-dingtalk-access-token` 来自
`POST /v1.0/oauth2/accessToken`），`userIds` 单批 ≤20；无链接用 `sampleMarkdown`，有
`deeplink_url` 用 `sampleActionCard2`。Markdown 正文为
`### <应用名> · <标题>` + 原文 content + `HH:mm · 来自 <发起方>`，与 OA body 同一套身份
信息。机器人结果记在收件人行的 `robot_process_query_key` / `robot_status` /
`robot_error`，**失败不得把工作通知标失败，反之亦然**。两个渠道各有全局开关
（控制台「钉钉 · 服务号」卡片的「通知渠道」子块）：`IntegrationSettings.dingtalk_notify_robot_enabled`
（默认开启；「服务号机器人」）关掉机器人第二通道；`dingtalk_notify_work_notice_enabled`
（默认开启；「工作通知」）关掉 OA 工作通知，此时投递不再调用 `asyncsend_v2`，收件人终态改由
机器人结果推进（机器人成功记 `sent` 且 `dingtalk_task_id` 留空，对账任务据此跳过；机器人失败记
`failed` + `error_code=ROBOT_REJECTED`）。两个开关不得同时关闭，设置接口会以 422 拒绝。

工作通知钉钉载荷固定为 `msgtype: oa`（不再发送 markdown / text / action_card）：

- **钉钉会改写 `head.text`。** 官方「消息类型与数据格式」写明：发送**工作通知**时，
  `oa.head.text` 会被替换为当前发送应用（`agent_id` 所属钉钉应用，即公司服务号）在开放
  平台登记的名称，请求体里的 `head.text` 对收件人不可见。因此调用应用的中文身份不能靠页
  眉传达。
- **色带仍有效。** `head.bgcolor` 文档未说会替换；取应用可选字段 `notify_head_bgcolor`
  （8 位 ARGB），未设置时按 app id 哈希在六色调色板中取稳定色带。不同应用在钉钉里是不同
  颜色的标题块。EasyAuth 自己发出的通知（如 `easyauth-lifecycle`）色带固定 `FF1F6FEB`。
- **`body.title` 前缀承载调用方中文名。** 合成为 `<应用中文名> · <通知标题>`。应用中文名
  取 `app_display_name`（若请求提供）否则 `App.name`，永不回落 `app_key`；EasyAuth 自身
  通知用站点标题，缺省「统一身份认证」。只截断通知标题部分，永不截断应用名。钉钉建议
  `body.title` 50 字以内，合成标题压到 40 字。`head.text` 仍按登记名填写（非工作通知场景
  才看得见），但工作通知上被钉钉覆盖，不能当作产品口径。
- `body.content` 为剥掉 markdown 标记后的纯文本，保留换行。旧 SDK 的 `template` 字段被
  忽略（不再发送 markdown / text / action_card）。
- `body.form` **始终**含 `时间`（Asia/Shanghai `YYYY-MM-DD HH:mm:ss`），避免钉钉对「同一
  用户同一天相同内容」静默去重。请求可附带 `fields: [{key, value}]`（例如「来自」），至
  多 5 项（加上「时间」后钉钉最多显示 6 条）；不得使用保留键「时间」。`key`/`value` 长度
  是卡片展示约束，不是钉钉硬限制。
- 若请求带 `deeplink_url`，写入 `message_url`。旧 SDK 的 `deeplink_title` 以及其它未知
  字段一律忽略，不得 422。移除条件：EasyLearning 等下游升级到不再发送旧字段的 SDK 之后，
  再考虑把 `template` / `deeplink_title` 收成 422。

- 目录作用域只能从控制台返回的权威列表里选；作用域失效会让健康检查 unhealthy，越界收件人
  记 `USER_SCOPE_MISMATCH`。
- 每个 App 最多一条 active 通道；每次更新创建新版本。
- **消息受理时冻结通道版本**，之后换通道不影响已受理消息的目录作用域。
- 全局集成设置里服务号 secret 为写入型字段；控制台不回显 secret，连通性失败也不暴露钉钉底层错误原文。

### 状态语义

| 状态 | 含义 |
| --- | --- |
| `202`（受理） | 消息已入库排队，**不代表发送成功** |
| `sent` | 最低可靠保证：已成功调用钉钉发送接口 |
| `delivered` | 仅来自钉钉明确返回的 read/unread 回执名单 |

`delivered` **不是**已读、不是审批知悉、不是合规送达证据。拿不到明确名单时保持 `sent`，
不做 24 小时乐观收敛。

`dedup_key` 是永久幂等键（数据库唯一约束；同 key 不同 payload 返回 `409`），语义与审批
`biz_key` 对齐。

## 5. 钉钉平台硬限制

发送走旧版 `asyncsend_v2`（官方无新版替代）。官方对工作通知的警示原文是：
**"超出以下限制次数后，接口返回成功，但用户无法接收到"**——所以下面几条不是建议，是必须在
设计里吸收的事实。

| 限制 | 数字 | 影响 |
| --- | --- | --- |
| `userid_list` 单次上限 | 100 | 投递批大小固定为 100 |
| 单次任务接收人 | ≤5000（企业内部应用） | 契约单请求上限 500，远低于此 |
| **相同内容对同一用户** | **一天 1 次** | ① 天然吸收崩溃重发；② 两条内容完全相同的消息，第二条会静默失败——下游必须在 content 里带业务变量（任务名、日期等） |
| 单应用对单人 | 500 条/天 | 正常量级碰不到；碰到时回执标 failed |
| 接收速率 | 每分钟 ≤5000 人次 | 报错型频控 → throttled + 120 秒退避 |
| 消息体 | ≤2048 字节 | API 受理时前置校验 |
| 应用×接口 QPS | ≤20/s | 平台通用频控 |
| **月调用量** | 标准版（免费）**全组织 5000 次/月** | 工作通知**计入**该额度（不在豁免清单内） |

回执窗口 24 小时，进度窗口 7 天。

> **上线前必须确认企业的钉钉版本。** 若是标准版，按"发送 + 对账×2"的调用系数，月安全预算
> 约 1600 条消息；要么升级专业版，要么关闭对账并压缩配额。

发送工作通知不需要额外权限点（应用创建时默认带消息通知接口权限）。access_token 复用现有获取
与缓存逻辑（7200 秒有效期，提前 120 秒刷新）。

## 6. 限流与审计

限流复用 `config/rate_limit.py` 的固定窗口原语，沿用"认证失败按 IP、业务按 credential/app"
的双层模式。所有 `429` 都带 `Retry-After`。

| namespace | 维度 | 默认阈值 |
| --- | --- | --- |
| `directory-authfail` / `notify-authfail` | IP | 30 次 / 300s |
| `directory-rate` | credential | 240 次 / 60s |
| `notify-post-rate` | app | 60 次 / 60s |
| `notify-daily-quota` | app | 5000 收件人·次 / 自然日 |
| `notify-status-rate` | credential | 240 次 / 60s |

通知写操作按 app 而非 credential 限流——多配几条凭据不应该放大配额。

审计动作：`app_capability_enabled` / `app_capability_disabled`、`app_directory_queried`、
`app_notify_accepted` / `app_notify_rejected`、`notify_delivered`、
`notify_delivery_exhausted`。

两条记录口径：

- **目录搜索不记检索词原文**（可能含人名隐私），只记端点、q 是否非空、结果数、凭据 id；
  且 list 搜索按"应用 × 端点 × 小时"聚合成一条，避免选人器每次击键都膨胀审计表。
  detail / manager / subordinates 和全部通知事件仍逐次记录。
- **通知不记正文**。审计目标是"谁发了、发给谁、多大量"，不是留存内容副本；正文本体留在
  `NotifyMessage` 表内，受保留期约束（见[数据保留与自动清理](../operations/data-retention.md)）。

## 7. 无 SSRF 面

通知出站目标是常量域名（`oapi.dingtalk.com` / `api.dingtalk.com`），不接受调用方提供的 URL
作为请求目标。`deeplink_url` 只作为消息载荷透传给钉钉，EasyAuth 从不请求它。
