# API 契约（权威版）：公共用户目录 + 统一钉钉通知

> 第 1 篇（权威契约）。本文是下游消费端适配器的唯一实现依据；与
> `PROMPT-easyproject-design.md` 第 6 节所引草案的全部差异见文末 §X 对照表。
> 落库模型见第 2 篇，投递语义见第 3 篇，钉钉侧限制出处见第 4 篇。

## §0 通则（两组端点共用）

### 0.1 鉴权

与现有公共 API 完全一致（`docs/api/easyauth-public-api.md` §鉴权）：

- `Authorization: Bearer <token>`，token 二选一：
  - 静态应用 token（`eat_` 前缀，EasyAuth console 签发）；
  - OAuth2 client_credentials 换取的 access token（`POST /oauth/token`，有效期 3600s）。
- **路径中的 `{app_key}` 必须与凭据所属应用一致**，不一致返回 `403 PERMISSION_DENIED`。
- 额外前置条件：超管开通应用的 `directory` / `notify` 平台能力，
  App owner 再将能力授予调用的具体 credential。应用层与凭据层必须同时通过；
  任一层缺失都返回 `403 PERMISSION_DENIED`。manifest 声明不会自动开通或授权。

### 0.2 目录引用（directory reference）约定 —— 全契约统一

- 对外用户标识沿用权限 API 的既有语义：**`user_id` = Authentik 用户标识
  （`UserMirror.authentik_user_id`，即 OIDC `sub`）**，与
  `GET /api/v1/apps/{app_key}/users/{user_id}/permissions` 同一取值。
- **`user_id` 仅在该员工至少完成过一次 SSO 登录后存在**（EasyAuth 的 UserMirror
  在首次 OIDC 登录时创建）；全量钉钉目录中未登录过的员工 `user_id` 为 `null`。
- 用户条目返回包含目录源与企业作用域的 opaque `user_ref`，部门条目返回同语义的
  opaque `department_ref`。消费方必须原样保存和回传，不得拼接、解码或依赖内部格式。
  路径 `{user_ref}`、`manager_id`、通知 `recipients[]`、`department_id` / `parent_id`
  过滤都应传对应条目返回的 ref。
- 旧引用仅作兼容输入：

| 形式 | 含义 | 示例 |
|---|---|---|
| 裸字符串 | `user_id`（authentik_user_id） | `"f7c31a09e5..."` |
| `dt:` 前缀 | 钉钉 userid（`dingtalk_user_id`） | `"dt:manager8836"` |
| 原始部门 ID | 钉钉部门 ID | `"460001"` |

- legacy 引用只在全部目录作用域中唯一匹配时解析；多作用域匹配返回
  `409 CONFLICT`（`details.reason=ambiguous_user_ref|ambiguous_department_ref`，并附
  `candidate_refs`）。在 directory endpoints 中，畸形 scoped ref 返回
  `422 VALIDATION_ERROR`（`details.reason=invalid_directory_ref`）。notify POST 的
  收件人解析是异步受理的一部分：请求体结构合法时，畸形/未知 ref 为逐收件人
  `failed(USER_NOT_FOUND)`，legacy 歧义为 `failed(USER_AMBIGUOUS)`，不以 HTTP
  409/422 拒绝整条消息。

### 0.3 错误结构与错误码

复用既有统一结构，无新增错误码：

```json
{"error": {"code": "VALIDATION_ERROR", "message": "…", "details": {}}}
```

| code | HTTP | 本契约中的触发 |
|---|---|---|
| `AUTHENTICATION_FAILED` | 401 | 凭据无效/应用行不存在 |
| `PERMISSION_DENIED` | 403 | app_key 不匹配 / 应用禁用 / App 能力未开通 / credential 能力未授权 |
| `VALIDATION_ERROR` | 422 | 参数缺失/格式错/超长（含 directory endpoint 的畸形 scoped ref、msg 2048 字节超限） |
| `NOT_FOUND` | 404 | 用户/消息不存在或不属于本 app |
| `CONFLICT` | 409 | dedup_key 载荷冲突、目录快照变化或 legacy 目录 ref 跨企业歧义 |
| `THROTTLED` | 429（带 `Retry-After` 头） | 速率/每日配额超限 |
| `DEPENDENCY_UNAVAILABLE` | 503 | 通知 App 未配置可用通道；目录端点是纯本地镜像查询 |
| `INTERNAL_ERROR` | 500 | 服务端错误 |

### 0.4 分页约定

对齐现有审批列表（非草案的 `{items, total}`，见差异 D-2）：

- 请求：`page`（默认 1）、`page_size`（默认 20；目录用户列表上限 **200**，
  其余列表上限 100）；
- 响应：`{"data": [...], "pagination": {"page", "page_size", "total_items", "total_pages"}}`。

### 0.5 时间与编码

- 时间戳一律 ISO 8601 带时区（如 `"2026-07-16T10:00:00+08:00"`）；
- 响应 UTF-8，中文不转义。

---

## §D 公共用户目录 API

数据来源：EasyAuth 内的钉钉目录镜像，目标同步周期为 300s，
但故障时可以滞后更久。
所有目录端点返回 `Cache-Control: private, max-age=60` 和多企业
`directory_snapshot`。新鲜度以 EasyAuth 本地成功事务提交时间判定；
消费方不得只根据固定 300s 假设快照权威。

条目返回 `source_slug`、`corp_id`、`user_ref` / `department_ref`、`email`、
`mobile`、`employee_number`、`status` 和保留的 `active`；用户条目不返回 unionId
和完整主管链。联系与工号字段属员工敏感信息，
不得写入日志或当作认证/授权事实。

### D1. `GET /api/v1/apps/{app_key}/directory/users` —— 搜索/分页列表

**查询参数**（全部可选，AND 组合）：

| 参数 | 说明 |
|---|---|
| `q` | 关键字，对 `name`/`title`/`dingtalk_user_id` 做大小写不敏感的子串匹配。空串等同省略。**不支持拼音检索**（镜像无拼音数据）；选人器的拼音匹配为消费方职责——`page_size=200` 允许把全员目录拉到本地缓存后客户端匹配（数百人规模 1~2 页即全量） |
| `department_id` | D5 返回的 `department_ref`，过滤该作用域内的**直接成员**（不含子部门） |
| `manager_id` | 主管条目返回的 `user_ref`，过滤同一作用域内的**直接下属**（等价于 D4） |
| `include_inactive` | `"true"` 时包含禁用/离职用户，默认只返回 active |
| `snapshot_id` | 后续页传回首页 `directory_snapshot.snapshot_id`；快照不一致或查询期间变化返回 `409 CONFLICT` |
| `page` / `page_size` | 见 §0.4，page_size 上限 200 |

**稳定排序**：`name`、`source_slug`、`corp_id`、`dingtalk_user_id` 依次升序。

**成功响应（200）**：

```json
{
  "data": [
    {
      "user_id": "f7c31a09e5b24f8d9a1c",
      "dingtalk_user_id": "user0123",
      "source_slug": "dingtalk",
      "corp_id": "corp-demo",
      "user_ref": "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:dXNlcjAxMjM",
      "name": "李小明",
      "avatar_url": "https://static-legacy.dingtalk.com/media/xxx.jpg",
      "title": "后端工程师",
      "email": "xiaoming@example.com",
      "mobile": "13800000000",
      "employee_number": "ET-00123",
      "status": "active",
      "departments": [
        {"department_id": "460001", "source_slug": "dingtalk", "corp_id": "corp-demo", "department_ref": "dept:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:NDYwMDAx", "name": "研发部"}
      ],
      "active": true
    },
    {
      "user_id": null,
      "dingtalk_user_id": "user0456",
      "source_slug": "dingtalk",
      "corp_id": "corp-demo",
      "user_ref": "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:dXNlcjA0NTY",
      "name": "王新人",
      "avatar_url": "",
      "title": "测试工程师",
      "email": "",
      "mobile": "",
      "employee_number": "ET-00456",
      "status": "active",
      "departments": [
        {"department_id": "460001", "source_slug": "dingtalk", "corp_id": "corp-demo", "department_ref": "dept:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:NDYwMDAx", "name": "研发部"},
        {"department_id": "470001", "source_slug": "dingtalk", "corp_id": "corp-demo", "department_ref": "dept:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:NDcwMDAx", "name": "质量委员会"}
      ],
      "active": true
    }
  ],
  "pagination": {"page": 1, "page_size": 20, "total_items": 2, "total_pages": 1},
  "directory_snapshot": {
    "snapshot_id": "8f4b7c...",
    "snapshots": [{
      "source_slug": "dingtalk",
      "corp_id": "ding-corp-a",
      "generation": 42,
      "status": "success",
      "snapshot_at": "2026-07-16T10:00:00+08:00",
      "snapshot_at_status": "valid",
      "stale": false
    }],
    "stale": false,
    "complete": true,
    "authoritative": true
  }
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `user_id` | Authentik 用户标识；**未登录过 EasyAuth 的员工为 `null`**（§0.2） |
| `dingtalk_user_id` | 原始钉钉 userid；不能单独作为跨企业键 |
| `source_slug` / `corp_id` / `user_ref` | 目录作用域与 opaque canonical 用户引用；下游保存并原样传回 |
| `avatar_url` | 可为空串（无头像） |
| `title` | 职位，可为空串 |
| `email` / `mobile` / `employee_number` | 镜像中的联系邮箱、手机号和工号，均可为空串 |
| `status` | `active` / `disabled` / `departed` |
| `departments` | 直接所属部门（钉钉支持多部门），每项带 scoped `department_ref` |
| `active` | 目录状态是否在职可用（禁用/离职为 `false`） |

`include_inactive=true` 包含从最新权威快照消失后保留的 tombstone。
这类用户不物理删除，返回 `status: "departed"`、`active: false`，部门与主管为空。

**`directory_snapshot` 语义**：顶层含 `snapshot_id`、`snapshots`、`stale`、
`complete`、`authoritative`。`snapshots` 每个 source/corp 一项，含 `source_slug`、
`corp_id`、`generation`、`status`、`snapshot_at`、`snapshot_at_status`、`stale`；
`snapshot_at_status` 取 `valid` / `missing` / `invalid` / `future`。只有
`authoritative == true`（即 complete 且不 stale）时，消费方才可将「未出现」
用于本地离职/停用收敛。

### D2. `GET /api/v1/apps/{app_key}/directory/users/{user_ref}` —— 详情

`user_ref` 取 §0.2 任一形式。

**成功响应（200）**：D1 条目全部字段，另加 `manager`；
根对象同时含上文定义的 `directory_snapshot`（下例省略该通用块）：

```json
{
  "user_id": "f7c31a09e5b24f8d9a1c",
  "dingtalk_user_id": "user0123",
  "source_slug": "dingtalk",
  "corp_id": "corp-demo",
  "user_ref": "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:dXNlcjAxMjM",
  "name": "王小明",
  "avatar_url": "https://…",
  "title": "后端工程师",
  "email": "xiaoming@example.com",
  "mobile": "13800000000",
  "employee_number": "ET-00123",
  "status": "active",
  "departments": [{"department_id": "460001", "source_slug": "dingtalk", "corp_id": "corp-demo", "department_ref": "dept:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:NDYwMDAx", "name": "研发部"}],
  "active": true,
  "manager": {
    "user_id": null,
    "dingtalk_user_id": "manager8836",
    "source_slug": "dingtalk",
    "corp_id": "corp-demo",
    "user_ref": "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:bWFuYWdlcjg4MzY",
    "name": "张主管",
    "title": "研发经理",
    "email": "manager@example.com",
    "mobile": "13900000000",
    "employee_number": "ET-00008",
    "status": "active",
    "active": true
  }
}
```

- `manager` 为直接主管摘要，无主管（如老板本人）时为 `null`。
- 引用不存在 → `404 NOT_FOUND`。
- 边界：从权威目录消失的用户保留 tombstone，返回
  `status: "departed"`、`active: false`、`departments: []`、`manager: null`。
- 仅剩历史 `UserMirror` 且无法确定目录源时，`source_slug` 为空串，`corp_id` 取
  其钉钉企业字段，`user_ref` 回落为全局唯一 Authentik `user_id`，不伪造 scoped ref。

### D3. `GET /api/v1/apps/{app_key}/directory/users/{user_ref}/manager` —— 直接主管

**成功响应（200）**：D2 中 `manager` 对象的同款结构（含 `departments` 与
`avatar_url`，即完整的 D1 条目形状）。

失败语义（`details.reason` 供程序分支）：

| 情形 | 响应 |
|---|---|
| `user_ref` 不存在 | `404 NOT_FOUND`，`details: {"reason": "user_not_found"}` |
| 用户存在但无主管 | `404 NOT_FOUND`，`details: {"reason": "no_manager"}` |

### D4. `GET /api/v1/apps/{app_key}/directory/users/{user_ref}/subordinates` —— 直接下属

- 仅直接下属（一层），仅 active，全量不分页（单主管直属规模有限）；
- 排序同 D1。

**成功响应（200）**：

```text
{"data": [ {…D1 条目…}, … ]}
```

`user_ref` 不存在 → `404`（`reason: "user_not_found"`）；存在但无下属 →
`200` 空 `data`。

### D5. `GET /api/v1/apps/{app_key}/directory/departments` —— 部门列表

| 参数 | 说明 |
|---|---|
| `parent_id` | 可选。省略 → 全量扁平列表；空串 → 所有作用域的根部门；传返回的 `department_ref` → 该作用域内的直接子部门 |

**成功响应（200）**：

```json
{
  "data": [
    {"department_id": "1", "source_slug": "dingtalk", "corp_id": "corp-demo", "department_ref": "dept:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:MQ", "parent_id": "", "name": "杰发科技", "order": 0},
    {"department_id": "460001", "source_slug": "dingtalk", "corp_id": "corp-demo", "department_ref": "dept:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:NDYwMDAx", "parent_id": "1", "name": "研发部", "order": 10}
  ]
}
```

- 根部门 `parent_id` 为空串；
- 稳定排序：`order`、`source_slug`、`corp_id`、`department_id` 依次升序；
- `parent_id` 不存在 → `200` 空 `data`（与「存在但无子部门」不区分，
  部门树遍历不需要该区分）。

### D6. 目录端点限流

| 项 | 值 |
|---|---|
| 每凭据速率 | 240 次 / 60s（全部目录端点共享一个桶） |
| 认证失败 | 每 IP 30 次 / 300s |

选人器按键即查的场景请在消费方做防抖（建议 ≥300ms）与 60s 结果缓存。

---

## §N 统一通知 API（钉钉工作通知）

底层通道：钉钉工作通知 asyncsend_v2（第 4 篇）。**API 为异步受理语义**：
POST 成功仅代表 EasyAuth 已落库并排程投递；投递结果通过 N4 查询。
每个 App 必须由 owner 在自己的 workspace 配置独立、版本化的钉钉通知通道。
通道绑定权威目录作用域 `(directory_source_slug, corp_id)`；消息受理时冻结当时
通道版本，后续替换活动通道不改写旧消息的发送身份或作用域。

### N1. 收件人语义

- `recipients` 元素应为目录返回的 opaque `user_ref`，**1~500 个非空字符串**，
  每个最多 **4096 字符**；目录返回的最大 v1 canonical ref 可完整原样传入，不截断；
- 受理时同步解析：解析成功的重复引用按
  `(source_slug, corp_id, dingtalk_user_id)` 合并去重；不同 source/corp 下相同 userid
  不是同一收件人；
- 解析失败的收件人**不阻塞整体受理**，直接成为终态 `failed` 收件人记录
  （`error_code` 注明原因，见 N4 表）——包括全部解析失败的极端情形
  （消息立即进入 `failed` 终态）；
- 仅允许通知 active 目录用户；禁用/离职 → `failed(USER_INACTIVE)`
  （范围裁决见第 5 篇 §3）；不属于冻结通道作用域 →
  `failed(USER_SCOPE_MISMATCH)`。

### N2. `POST /api/v1/apps/{app_key}/notify/messages` —— 发送

**请求体**：

```json
{
  "recipients": ["dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:dXNlcjAxMjM", "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:bWFuYWdlcjg4MzY"],
  "template": "action_card",
  "title": "任务逾期升级",
  "content": "### 任务已逾期 3 天\n**接口联调排期**\n负责人: 王小明",
  "deeplink_url": "https://eproject.jiefakj.com/zh-CN/tasks/123",
  "deeplink_title": "查看任务",
  "dedup_key": "overdue-escalate:123:2026-07-16",
  "biz_tag": "overdue_escalation"
}
```

| 字段 | 必填 | 约束 |
|---|---|---|
| `recipients` | 是 | 1~500 个非空用户引用，每个 ≤4096 字符（N1） |
| `template` | 是 | `"text"` / `"markdown"` / `"action_card"` |
| `title` | markdown、action_card 必填 | ≤100 字符；text 模板忽略此字段 |
| `content` | 是 | text=纯文本；markdown/action_card=钉钉 markdown 语法。**硬限制：组装后的钉钉 msg JSON ≤ 2048 字节（UTF-8）**，纯中文正文经验值约 550 字；超限 `422` |
| `deeplink_url` | action_card 必填，其余忽略 | ≤500 字符；`https://` 直链（移动端钉钉内 H5 打开、PC 端系统浏览器打开），或 `dingtalk://dingtalkclient/page/link?...` 协议链（PC 侧边栏场景，内嵌 url 仍须 https），详见第 4 篇 §3.1 |
| `deeplink_title` | 否 | action_card 按钮文案，≤20 字符，默认 `"查看详情"` |
| `dedup_key` | 否 | ≤128 字符。**app 内永久幂等键**（非时间窗口）：应编入事件发生标识，如 `task-assigned:123:v2`、`overdue-remind:123:2026-07-16`；想再次发送就换 key |
| `biz_tag` | 否 | ≤64 字符，业务分类标签，仅用于统计与运维检索 |

**内容注意（钉钉侧约束，第 4 篇 §4.1）**：钉钉对「相同内容 + 同一收件人 +
同一天」服务端去重（静默丢弃，事后标 `failed(DINGTALK_DUPLICATE)`）。
请在 content 中带上业务变量（任务名、日期、序号），不要发字面完全相同的正文。

**响应**：

| 情形 | HTTP | 响应体 |
|---|---|---|
| 新受理 | **202** | 见下 `accepted: true`；仅表示已落库排程，不表示已发送 |
| `dedup_key` 命中且载荷一致（幂等重放） | **200** | 同结构，`accepted: false`，`message_id` 为首次受理的 ID |
| `dedup_key` 命中但载荷不同 | **409 CONFLICT** | 统一错误结构 |
| 参数问题 | **422 VALIDATION_ERROR** | 请求体级校验，整条请求不落部分行；含 recipients 数量/空值/单项 >4096 字符，`details.field` 指明字段 |
| 速率/配额超限 | **429 THROTTLED** + `Retry-After` | — |
| 凭据无效 | **401 AUTHENTICATION_FAILED** | 不持续重试 |
| App / credential 缺 `notify` | **403 PERMISSION_DENIED** | 修正 capability 配置 |
| App 通知通道未配置 | **503 DEPENDENCY_UNAVAILABLE** | 由 App owner 配置并测试通道 |

```json
{
  "message_id": "0d9f5c1e-7a42-4b8e-9c3d-2f1a6b8e4d70",
  "accepted": true,
  "status": "pending",
  "recipient_total": 2,
  "recipient_rejected": 0
}
```

- `recipient_total`：解析合并后的收件人数（含受理时即失败者）；
- `recipient_rejected`：受理时即判终态失败的收件人数（畸形/未知/歧义、非 active、
  scope mismatch）。
- 每个输入引用以 `raw_ref` 原样持久化和回显，不截断 opaque ref。

### N3. 投递保证与限流

- **至少一次投递**：EasyAuth 侧落库 + outbox + 重试（1m/5m/30m/2h 四轮退避；
  钉钉分钟级频控另按 120s 退避），耗尽标 `failed(EXHAUSTED)`；极小概率的崩溃
  重发由钉钉「相同内容同人一天 1 次」的服务端去重吸收；
- **每 app 限流**（超限 `429` + `Retry-After`）：

| 项 | 默认值（可按 app 配置） |
|---|---|
| POST 速率 | 60 次 / 60s（按 app，多凭据共享） |
| 每日收件人配额 | 5000 收件人·次 / 自然日（Asia/Shanghai） |
| GET 状态查询 | 240 次 / 60s（按凭据） |

### N4. `GET /api/v1/apps/{app_key}/notify/messages/{message_id}` —— 投递状态

**成功响应（200）**：

```json
{
  "message_id": "0d9f5c1e-7a42-4b8e-9c3d-2f1a6b8e4d70",
  "status": "partially_failed",
  "template": "action_card",
  "biz_tag": "overdue_escalation",
  "dedup_key": "overdue-escalate:123:2026-07-16",
  "created_at": "2026-07-16T10:00:00+08:00",
  "completed_at": "2026-07-16T10:03:12+08:00",
  "recipient_total": 2,
  "recipient_sent": 1,
  "recipient_failed": 1,
  "recipients": [
    {
      "raw_ref": "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:dXNlcjAxMjM",
      "user_id": "f7c31a09e5b24f8d9a1c",
      "dingtalk_user_id": "user0123",
      "status": "delivered",
      "error_code": "",
      "error": "",
      "sent_at": "2026-07-16T10:00:04+08:00",
      "delivered_at": "2026-07-16T10:01:00+08:00"
    },
    {
      "raw_ref": "dt:v1:ZGluZ3RhbGs:Y29ycC1kZW1v:Zm9ybWVydXNlcjAx",
      "user_id": null,
      "dingtalk_user_id": "formeruser01",
      "status": "failed",
      "error_code": "USER_INACTIVE",
      "error": "目录状态为 departed, 拒绝投递。",
      "sent_at": null,
      "delivered_at": null
    }
  ]
}
```

`message_id` 不存在或属于其它 app → `404 NOT_FOUND`。

**消息聚合 `status`**：

| 值 | 含义 |
|---|---|
| `pending` | 已受理，投递未开始 |
| `sending` | 投递进行中（含重试间隙） |
| `completed` | 全部收件人 `sent` 或 `delivered` |
| `partially_failed` | 部分失败 |
| `failed` | 全部失败 |

**收件人 `status`**：

| 值 | 含义 | 终态 |
|---|---|---|
| `pending` | 待投递 | 否 |
| `throttled` | 钉钉分钟级频控拒收，待重试 | 否 |
| `sent` | 钉钉已受理（**注意：受理≠送达**，钉钉可能静默流控） | 半终态 |
| `delivered` | 钉钉明确 send-result 回执将 userid 列入 read/unread 名单 | 是 |
| `failed` | 终态失败，看 `error_code` | 是 |

**`error_code` 枚举**：

| 值 | 含义 | 消费方建议动作 |
|---|---|---|
| `USER_NOT_FOUND` | scoped ref 畸形或引用无法解析到目录用户 | 检查引用来源，刷新目录缓存 |
| `USER_AMBIGUOUS` | legacy 引用在多个企业作用域匹配 | 刷新目录并改传返回的 scoped `user_ref` |
| `USER_SCOPE_MISMATCH` | 用户不属于消息冻结通道的目录作用域 | 修正通道或收件人业务规则，不重试 |
| `NO_DINGTALK_ID` | 用户存在但无钉钉绑定（罕见） | 无法钉钉触达，走业务兜底 |
| `USER_INACTIVE` | 用户已禁用/离职 | 更新本地成员状态 |
| `DINGTALK_REJECTED` | 钉钉回执：无效 userid 或发送失败 | 少量可忽略，批量出现联系平台方 |
| `DINGTALK_DUPLICATE` | 钉钉判定相同内容同人一天已发过 | 调整 content 带业务变量 |
| `DINGTALK_DAILY_LIMIT` | 钉钉单应用对单人 500 条/日超限 | 检查是否有通知风暴 bug |
| `EXHAUSTED` | EasyAuth 重试耗尽 | 平台侧会告警；业务可换 dedup_key 重发 |

canonical 收件人行以 `(message, source_slug, corp_id, dingtalk_user_id)` 唯一；仅对
缺少完整 source/corp 的历史 legacy 行保留独立的 `(message, dingtalk_user_id)`
兼容唯一约束。合法 notify 请求中的畸形/未知/歧义/scope mismatch 都通过 202 后的
逐收件人错误表达，而不是 directory endpoints 的 HTTP 409/422 语义。

**状态时效**：`sent → delivered/failed` 的升级依赖回执对账任务（60s 周期，
send-result 查询窗口 24h）；对账属尽力而为，`sent` 是消费方可依赖的最低保证。
无明确 read/unread/失败名单归类时保持 `sent`，但推进持久化
`last_reconciled_at`；超过 24h 也不推断为 `delivered`。每轮公平轮转最多 50 个
唯一 `(channel, task_id)`；failed 与剩余 sent 并存时消息为 `partially_failed`。
`delivered` 不表示已读，不得作为审批知悉、法务送达或其他合规事实。事件型通知
（分配、@提及）无需轮询本端点；需要闭环确认的场景（验收结果）建议延迟
2~5 分钟单次查询而非轮询。

---

## §X 与草案的差异对照表

| # | 草案 | 权威版 | 原因 |
|---|---|---|---|
| D-1 | `GET /api/v1/directory/...` | `GET /api/v1/apps/{app_key}/directory/...` | 全部现有公共端点都以 `apps/{app_key}` 开头并强制「路径 app_key = 凭据 app_key」，目录/通知沿用同一鉴权不变量 |
| D-2 | 列表响应 `{items, total}` | `{data, pagination{page,page_size,total_items,total_pages}}` | 对齐既有审批列表分页结构，SDK/下游只需一套分页解析 |
| D-3 | `user_id` 恒存在 | `user_id` 可为 `null`；返回 opaque scoped `user_ref`，旧 `dt:` 仅兼容 | `UserMirror` 仅在首次 SSO 登录时创建，且原始钉钉 userid 可跨企业重复；canonical ref 同时解决未登录与作用域消歧 |
| D-4 | `department_id`、`manager_id` 过滤语义未定义 | 部门=直接成员（不递归）；manager=直接下属；新增 `include_inactive` | 契约必须可实现、语义无歧义 |
| D-5 | `departments?parent_id=` 返回"列表/树" | 只返回扁平列表（全量或直接子部门），树由消费方构建 | 避免嵌套树的深分页/局部更新歧义；部门量级小，扁平全量最简单 |
| D-6 | 隐含服务端拼音搜索 | 拼音检索为消费方职责，服务端仅子串匹配；`page_size` 上限放宽到 200 支持全量缓存 | 镜像数据源无拼音字段；自建拼音索引引入依赖与多音字错配，不值 |
| N-1 | `POST /api/v1/notify/messages` | `POST /api/v1/apps/{app_key}/notify/messages` | 同 D-1 |
| N-2 | `recipients: [user_id...]` | 元素传目录返回的 opaque scoped `user_ref` | 同 D-3，未登录员工也要能收通知，同时不得跨企业误投 |
| N-3 | `202 {message_id, accepted}` | 新受理 202 / 幂等命中 200（`accepted:false`）/ 载荷冲突 409；响应加 `status`、收件人计数 | 对齐审批 `biz_key` 的既有幂等语义（201/200 + payload_hash 冲突检测） |
| N-4 | `dedup_key` 幂等未定窗口 | app 内**永久**幂等（DB 唯一约束），key 应编入事件发生标识 | 窗口幂等依赖易失存储；永久键语义更强且实现更简单，重发诉求用换 key 表达 |
| N-5 | 收件人状态 `pending/sent/failed/throttled`，字段 `error?` | 增加 `delivered`；`error` 拆为机器可读 `error_code` + 人读 `error`；补完整枚举 | 钉钉「受理≠送达」；`delivered` 仅由明确 read/unread 回执产生，scope/歧义和静默流控均需机器可读原因 |
| N-6 | `template/title/content/deeplink_url` 无约束 | 明确各模板必填项、长度与 2048 字节硬限、https 校验；新增可选 `deeplink_title` | 全部来自钉钉官方硬限制（第 4 篇），受理期前置校验早于钉钉拒收 |
| N-7 | 收件人数量未定 | 单请求 ≤500 | 钉钉批 100/次 + 单任务回执能力约束，500 = 5 批，兼顾提醒风暴场景与任务时长 |
| N-8 | — | 新增每 app 速率（60/min）与每日配额（5000 收件人·次）及 429 语义 | 通知目标范围放开为全员 active 后的爆炸半径控制（第 5 篇 §3） |
