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

### 0.2 用户引用（user reference）约定 —— 全契约统一

- 对外用户标识沿用权限 API 的既有语义：**`user_id` = Authentik 用户标识
  （`UserMirror.authentik_user_id`，即 OIDC `sub`）**，与
  `GET /api/v1/apps/{app_key}/users/{user_id}/permissions` 同一取值。
- **`user_id` 仅在该员工至少完成过一次 SSO 登录后存在**（EasyAuth 的 UserMirror
  在首次 OIDC 登录时创建）；全量钉钉目录中未登录过的员工 `user_id` 为 `null`。
- 因此所有「接受用户引用」的位置（路径 `{user_ref}`、查询参数 `manager_id`、
  通知 `recipients[]` 元素）统一接受两种字符串形式：

| 形式 | 含义 | 示例 |
|---|---|---|
| 裸字符串 | `user_id`（authentik_user_id） | `"f7c31a09e5..."` |
| `dt:` 前缀 | 钉钉 userid（`dingtalk_user_id`） | `"dt:manager8836"` |

- 消费方惯用法：`user["user_id"] or f"dt:{user['dingtalk_user_id']}"`。
- 目录响应中 `dingtalk_user_id` **恒非空**（目录数据源就是钉钉目录镜像）。

### 0.3 错误结构与错误码

复用既有统一结构，无新增错误码：

```json
{"error": {"code": "VALIDATION_ERROR", "message": "…", "details": {}}}
```

| code | HTTP | 本契约中的触发 |
|---|---|---|
| `AUTHENTICATION_FAILED` | 401 | 凭据无效/应用行不存在 |
| `PERMISSION_DENIED` | 403 | app_key 不匹配 / 应用禁用 / App 能力未开通 / credential 能力未授权 |
| `VALIDATION_ERROR` | 422 | 参数缺失/格式错/超长（含 msg 2048 字节超限） |
| `NOT_FOUND` | 404 | 用户/消息不存在或不属于本 app |
| `CONFLICT` | 409 | dedup_key 已存在但载荷不同，或目录 `snapshot_id` 不一致/查询期间变化 |
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

数据来源：EasyAuth 内的钉钉目录镜像（每 300s 从 Authentik 同步）。
所有目录端点返回 `Cache-Control: private, max-age=60` 和多企业
`directory_snapshot`。新鲜度以 EasyAuth 本地成功事务提交时间判定；
消费方不得只根据固定 300s 假设快照权威。

条目返回 `email`、`mobile`、`employee_number`、`status` 和保留的
`active`；用户条目不返回 unionId、corp_id 和完整主管链。`corp_id` 只出现在
`directory_snapshot.snapshots[]` 作为多企业快照边界。联系与工号字段属员工敏感信息，
不得写入日志或当作认证/授权事实。

### D1. `GET /api/v1/apps/{app_key}/directory/users` —— 搜索/分页列表

**查询参数**（全部可选，AND 组合）：

| 参数 | 说明 |
|---|---|
| `q` | 关键字，对 `name`/`title`/`dingtalk_user_id` 做大小写不敏感的子串匹配。空串等同省略。**不支持拼音检索**（镜像无拼音数据）；选人器的拼音匹配为消费方职责——`page_size=200` 允许把全员目录拉到本地缓存后客户端匹配（数百人规模 1~2 页即全量） |
| `department_id` | 部门 ID（见 D5），过滤该部门**直接成员**（不含子部门；树形浏览逐级下钻即可） |
| `manager_id` | 用户引用（§0.2 两种形式均可），过滤其**直接下属**（等价于 D4） |
| `include_inactive` | `"true"` 时包含禁用/离职用户，默认只返回 active |
| `snapshot_id` | 后续页传回首页 `directory_snapshot.snapshot_id`；快照不一致或查询期间变化返回 `409 CONFLICT` |
| `page` / `page_size` | 见 §0.4，page_size 上限 200 |

**排序**：`name` 升序，再按 `dingtalk_user_id` 升序（稳定分页）。

**成功响应（200）**：

```json
{
  "data": [
    {
      "user_id": "f7c31a09e5b24f8d9a1c",
      "dingtalk_user_id": "user0123",
      "name": "李小明",
      "avatar_url": "https://static-legacy.dingtalk.com/media/xxx.jpg",
      "title": "后端工程师",
      "email": "xiaoming@example.com",
      "mobile": "13800000000",
      "employee_number": "ET-00123",
      "status": "active",
      "departments": [
        {"department_id": "460001", "name": "研发部"}
      ],
      "active": true
    },
    {
      "user_id": null,
      "dingtalk_user_id": "user0456",
      "name": "王新人",
      "avatar_url": "",
      "title": "测试工程师",
      "email": "",
      "mobile": "",
      "employee_number": "ET-00456",
      "status": "active",
      "departments": [
        {"department_id": "460001", "name": "研发部"},
        {"department_id": "470001", "name": "质量委员会"}
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
| `dingtalk_user_id` | 钉钉 userid，恒非空；通知收件与 `dt:` 引用用它 |
| `avatar_url` | 可为空串（无头像） |
| `title` | 职位，可为空串 |
| `email` / `mobile` / `employee_number` | 镜像中的联系邮箱、手机号和工号，均可为空串 |
| `status` | `active` / `disabled` / `departed` |
| `departments` | 直接所属部门（钉钉支持多部门），按 `department_id` 升序 |
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
  "name": "王小明",
  "avatar_url": "https://…",
  "title": "后端工程师",
  "email": "xiaoming@example.com",
  "mobile": "13800000000",
  "employee_number": "ET-00123",
  "status": "active",
  "departments": [{"department_id": "460001", "name": "研发部"}],
  "active": true,
  "manager": {
    "user_id": null,
    "dingtalk_user_id": "manager8836",
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

```json
{"data": [ {…D1 条目…}, … ]}
```

`user_ref` 不存在 → `404`（`reason: "user_not_found"`）；存在但无下属 →
`200` 空 `data`。

### D5. `GET /api/v1/apps/{app_key}/directory/departments` —— 部门列表

| 参数 | 说明 |
|---|---|
| `parent_id` | 可选。省略 → **全量扁平列表**（消费方按 `parent_id` 自建树，部门量级小，单响应完整返回，不分页）；传入 → 该部门的直接子部门 |

**成功响应（200）**：

```json
{
  "data": [
    {"department_id": "1", "parent_id": "", "name": "杰发科技", "order": 0},
    {"department_id": "460001", "parent_id": "1", "name": "研发部", "order": 10}
  ]
}
```

- 根部门 `parent_id` 为空串；
- 排序：`order` 升序，再 `department_id` 升序；
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
消息受理时冻结当时通道版本；后续替换活动通道不改写旧消息的发送身份。

### N1. 收件人语义

- `recipients` 元素为 §0.2 用户引用字符串，**1~500 个**；
- 受理时同步解析：重复引用（含 `user_id` 与 `dt:` 指向同一人）按解析后的钉钉
  userid 合并去重；
- 解析失败的收件人**不阻塞整体受理**，直接成为终态 `failed` 收件人记录
  （`error_code` 注明原因，见 N4 表）——包括全部解析失败的极端情形
  （消息立即进入 `failed` 终态）；
- 仅允许通知 active 目录用户；禁用/离职 → `failed(USER_INACTIVE)`
  （范围裁决见第 5 篇 §3）。

### N2. `POST /api/v1/apps/{app_key}/notify/messages` —— 发送

**请求体**：

```json
{
  "recipients": ["f7c31a09e5b24f8d9a1c", "dt:manager8836"],
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
| `recipients` | 是 | 1~500 个用户引用（N1） |
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
| 参数问题 | **422 VALIDATION_ERROR** | `details.field` 指明字段 |
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
- `recipient_rejected`：受理时即判终态失败的收件人数（解析失败/非 active）。

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
      "raw_ref": "f7c31a09e5b24f8d9a1c",
      "user_id": "f7c31a09e5b24f8d9a1c",
      "dingtalk_user_id": "user0123",
      "status": "delivered",
      "error_code": "",
      "error": "",
      "sent_at": "2026-07-16T10:00:04+08:00",
      "delivered_at": "2026-07-16T10:01:00+08:00"
    },
    {
      "raw_ref": "dt:formeruser01",
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
| `USER_NOT_FOUND` | 引用无法解析到目录用户 | 检查引用来源，刷新目录缓存 |
| `NO_DINGTALK_ID` | 用户存在但无钉钉绑定（罕见） | 无法钉钉触达，走业务兜底 |
| `USER_INACTIVE` | 用户已禁用/离职 | 更新本地成员状态 |
| `DINGTALK_REJECTED` | 钉钉回执：无效 userid 或发送失败 | 少量可忽略，批量出现联系平台方 |
| `DINGTALK_DUPLICATE` | 钉钉判定相同内容同人一天已发过 | 调整 content 带业务变量 |
| `DINGTALK_DAILY_LIMIT` | 钉钉单应用对单人 500 条/日超限 | 检查是否有通知风暴 bug |
| `EXHAUSTED` | EasyAuth 重试耗尽 | 平台侧会告警；业务可换 dedup_key 重发 |

**状态时效**：`sent → delivered/failed` 的升级依赖回执对账任务（60s 周期，
send-result 查询窗口 24h）；对账属尽力而为，`sent` 是消费方可依赖的最低保证。
无明确 read/unread/失败名单归类时保持 `sent`，超过 24h 也不推断为 `delivered`。
`delivered` 不表示已读，不得作为审批知悉、法务送达或其他合规事实。事件型通知
（分配、@提及）无需轮询本端点；需要闭环确认的场景（验收结果）建议延迟
2~5 分钟单次查询而非轮询。

---

## §X 与草案的差异对照表

| # | 草案 | 权威版 | 原因 |
|---|---|---|---|
| D-1 | `GET /api/v1/directory/...` | `GET /api/v1/apps/{app_key}/directory/...` | 全部现有公共端点都以 `apps/{app_key}` 开头并强制「路径 app_key = 凭据 app_key」，目录/通知沿用同一鉴权不变量 |
| D-2 | 列表响应 `{items, total}` | `{data, pagination{page,page_size,total_items,total_pages}}` | 对齐既有审批列表分页结构，SDK/下游只需一套分页解析 |
| D-3 | `user_id` 恒存在 | `user_id` 可为 `null`；`dingtalk_user_id` 恒存在；引入 `dt:` 前缀引用 | `UserMirror` 仅在首次 SSO 登录时创建，全量目录必然包含无 authentik 绑定的员工；此为数据事实而非设计取舍 |
| D-4 | `department_id`、`manager_id` 过滤语义未定义 | 部门=直接成员（不递归）；manager=直接下属；新增 `include_inactive` | 契约必须可实现、语义无歧义 |
| D-5 | `departments?parent_id=` 返回"列表/树" | 只返回扁平列表（全量或直接子部门），树由消费方构建 | 避免嵌套树的深分页/局部更新歧义；部门量级小，扁平全量最简单 |
| D-6 | 隐含服务端拼音搜索 | 拼音检索为消费方职责，服务端仅子串匹配；`page_size` 上限放宽到 200 支持全量缓存 | 镜像数据源无拼音字段；自建拼音索引引入依赖与多音字错配，不值 |
| N-1 | `POST /api/v1/notify/messages` | `POST /api/v1/apps/{app_key}/notify/messages` | 同 D-1 |
| N-2 | `recipients: [user_id...]` | 元素可为 `dt:` 前缀引用 | 同 D-3，未登录员工也要能收通知（正是引导登录的入口） |
| N-3 | `202 {message_id, accepted}` | 新受理 202 / 幂等命中 200（`accepted:false`）/ 载荷冲突 409；响应加 `status`、收件人计数 | 对齐审批 `biz_key` 的既有幂等语义（201/200 + payload_hash 冲突检测） |
| N-4 | `dedup_key` 幂等未定窗口 | app 内**永久**幂等（DB 唯一约束），key 应编入事件发生标识 | 窗口幂等依赖易失存储；永久键语义更强且实现更简单，重发诉求用换 key 表达 |
| N-5 | 收件人状态 `pending/sent/failed/throttled`，字段 `error?` | 增加 `delivered`；`error` 拆为机器可读 `error_code` + 人读 `error`；补七值枚举 | 钉钉「受理≠送达」；`delivered` 仅由明确 read/unread 回执产生，静默流控只能靠回执失败名单发现 |
| N-6 | `template/title/content/deeplink_url` 无约束 | 明确各模板必填项、长度与 2048 字节硬限、https 校验；新增可选 `deeplink_title` | 全部来自钉钉官方硬限制（第 4 篇），受理期前置校验早于钉钉拒收 |
| N-7 | 收件人数量未定 | 单请求 ≤500 | 钉钉批 100/次 + 单任务回执能力约束，500 = 5 批，兼顾提醒风暴场景与任务时长 |
| N-8 | — | 新增每 app 速率（60/min）与每日配额（5000 收件人·次）及 429 语义 | 通知目标范围放开为全员 active 后的爆炸半径控制（第 5 篇 §3） |
