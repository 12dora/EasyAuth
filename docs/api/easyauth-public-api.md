# EasyAuth 公共 API（下游应用契约）

## 范围

本文是**下游业务应用**接入 EasyAuth 的正式公共契约。所有接口均挂在 `/api/v1/` 下，仅接受应用级 Bearer 凭据。

**不在本契约范围内：**

- `/console/api/v1/*`：管理控制台私有 API（session + CSRF）
- `/portal/api/v1/*`：员工门户私有 API（session）
- 控制台/门户接口**不得**使用静态 app token 或 OAuth access token 作为管理/员工身份

相关文档：

- 控制台私有 API 目录：[`easyauth-console-api.md`](./easyauth-console-api.md)
- 员工门户私有 API：[`easyauth-portal-react-api.md`](./easyauth-portal-react-api.md)
- Python SDK：`sdk/python/`

## 鉴权

### Bearer 静态 Token

控制台为应用签发静态 token（明文一次性展示，前缀通常为 `eat_`）。

```http
Authorization: Bearer eat_...
```

### OAuth2 client_credentials

```http
POST /oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=...&client_secret=...
```

响应中的 `access_token` 作为 Bearer 使用。

### 路径与凭据绑定

URL 中的 `{app_key}` **必须**与 token 所属应用一致；否则返回 `403 PERMISSION_DENIED`。  
应用必须处于 active；凭据无效返回 `401 AUTHENTICATION_FAILED`。

`directory` 与 `notify` 还有双层授权门：超管先为 App 开通对应平台能力，
再由 App owner 把能力授予调用所用的具体凭据。任一层缺失都返回
`403 PERMISSION_DENIED`。manifest 顶层 `capabilities` 只表示应用声明需求，
不会自动开通 App 能力，也不会自动授权任何凭据。

## 统一错误结构

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "人类可读说明",
    "details": {}
  }
}
```

| code | 典型 HTTP | 含义 |
| --- | --- | --- |
| `VALIDATION_ERROR` | 400 / 405 / 422 | 方法、参数或结构无效 |
| `AUTHENTICATION_FAILED` | 401 | 缺少/无效 Bearer |
| `PERMISSION_DENIED` | 403 | app_key 与凭据不匹配等 |
| `NOT_FOUND` | 404 | 资源不存在 |
| `CONFLICT` | 409 | 版本冲突等 |
| `SEMANTIC_VALIDATION_ERROR` | 409 / 422 | 业务语义冲突或校验失败 |
| `DEPENDENCY_UNAVAILABLE` | 503 | 目录/钉钉等依赖不可用 |
| `THROTTLED` | 429 | 限流 |
| `INTERNAL_ERROR` | 500 | 服务内部错误 |

公共 API **不会**在响应中返回 token 明文、webhook secret、`dingtalk_process_code`、`form_mapping` 等密钥类字段。

---

## 1. 权限查询

### `GET /api/v1/apps/{app_key}/users/{user_id}/permissions`

查询用户在本应用下的当前授权快照。

**鉴权：** Bearer 应用凭据。

**成功响应：**

```json
{
  "user_id": "ak-user-1",
  "app_key": "easytrade",
  "groups": [
    {"key": "sales", "kind": "role", "name": "销售"}
  ],
  "grants": [
    {
      "permission": "order.view",
      "scope": "SELF",
      "source_type": "group",
      "source_key": "sales"
    }
  ],
  "grant_version": 3,
  "catalog_version": 12,
  "snapshot_version": "…",
  "expires_at": "2026-07-11T12:00:00+00:00"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `groups` | 用户当前所属授权组（`authorization_groups` 投影） |
| `grants` | 展开后的权限-scope 列表 |
| `grant_version` | 授权事实版本 |
| `catalog_version` | 目录版本 |
| `snapshot_version` | 快照版本（由 grant/catalog 等组成） |
| `expires_at` | 下游缓存过期建议时间 |
| `grants[].resolved` | 当 scope 为 `MANAGED_USERS` 时可能附带解析结果 |

目录瞬时故障时返回 `503 DEPENDENCY_UNAVAILABLE`，下游**不得**把缺失结果当作真实撤权。

---

## 2. Manifest 同步

### `POST /api/v1/apps/{app_key}/manifest-sync`

下游在部署/启动时推送权限模板 manifest。应用必须已注册；本端点**不会**创建新应用。  
版本单调递增 + content_hash 幂等。

**请求体：**

```json
{
  "manifest": {
    "schema_version": 1,
    "app": {"app_key": "easytrade", "name": "EasyTrade"},
    "scopes": [{"key": "SELF", "name": "本人"}],
    "permission_groups": [{"key": "order", "name": "订单"}],
    "permissions": [
      {
        "key": "order.view",
        "name": "查看订单",
        "group_key": "order",
        "supported_scopes": ["SELF"]
      }
    ],
    "lifecycle": {
      "handover_url": "/api/v1/easyauth/lifecycle/handover",
      "onboard_url": null,
      "capabilities": ["preview"]
    },
    "webhook": {"signing": "hmac-sha256"}
  },
  "base_url": "https://easytrade.example.com"
}
```

- `manifest.app.app_key` 必须与路径 `{app_key}` 一致。
- `base_url` 可选：用于将 lifecycle 相对路径补全为 webhook 绝对地址。

**成功响应：**

```json
{
  "app_key": "easytrade",
  "already_up_to_date": false,
  "template_version": 2,
  "catalog_version": 12
}
```

---

## 3. 审批实例

审批走钉钉流程；EasyAuth 负责模板映射、实例状态与结果 webhook 回调。

### `POST /api/v1/apps/{app_key}/approval-instances`

创建审批实例。同一 `biz_key` 幂等：相同 payload 返回既有实例（200）；不同 payload 返回 409。

**请求体：**

```json
{
  "template_key": "expense",
  "originator_user_id": "ak-user-1",
  "form": {"amount": "1000"},
  "biz_key": "order-42",
  "retry": false
}
```

**成功响应（201 新建 / 200 幂等命中）：**

```json
{
  "instance_id": "uuid",
  "template_key": "expense",
  "biz_key": "order-42",
  "status": "submitted",
  "submission_state": "submitted",
  "provider_correlation_key": "…",
  "originator_user_id": "ak-user-1",
  "created_at": "2026-07-11T10:00:00+00:00",
  "completed_at": null
}
```

### `GET /api/v1/apps/{app_key}/approval-instances`

列出本应用审批实例（分页）。

**查询参数：**

| 参数 | 说明 |
| --- | --- |
| `status` | 可选，按实例状态过滤 |
| `biz_key` | 可选 |
| `template_key` | 可选 |
| `page` | 默认 1 |
| `page_size` | 默认 20，最大 100 |

**成功响应：**

```json
{
  "data": [
    {
      "instance_id": "uuid",
      "template_key": "expense",
      "biz_key": "order-42",
      "status": "submitted",
      "submission_state": "submitted",
      "provider_correlation_key": "…",
      "originator_user_id": "ak-user-1",
      "created_at": "2026-07-11T10:00:00+00:00",
      "completed_at": null
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 1,
    "total_pages": 1
  }
}
```

列表会对条目执行陈旧提交恢复（`recover_stale_submission`），不破坏列表可用性。

### `GET /api/v1/apps/{app_key}/approval-instances/{instance_id}`

查询单实例状态（webhook 之外的轮询兜底）。仅能读取本应用实例。

---

## 4. 审批模板

### `GET /api/v1/apps/{app_key}/approval-templates`

列出本应用可用的**活跃**审批模板：

- 归属当前应用（`app = 本应用`），或
- 平台共用模板（`app is null`）

且 `is_active = true`。

**成功响应：**

```json
{
  "data": [
    {
      "key": "expense",
      "name": "费用审批",
      "form_schema": {
        "amount": {"type": "string", "required": true}
      },
      "is_active": true
    }
  ]
}
```

**刻意不返回：**

- `dingtalk_process_code`（钉钉流程编码，provider 侧秘密）
- `form_mapping`（业务字段 → 钉钉控件名，内部映射）

下游用 `form_schema` 构造发起表单即可。

---

## 5. 用户目录

数据来源为 EasyAuth 内的钉钉目录镜像（约每 300s 从 Authentik 同步）。
应用的 `directory` 平台能力和当前凭据的 `directory` 能力必须同时开启，
否则返回 `403 PERMISSION_DENIED`（文案：「应用未开通目录能力。」）。
所有目录端点返回 `Cache-Control: private, max-age=60`。

用户引用约定：`user_id` = Authentik 用户标识（可空，未 SSO 登录过的员工为 `null`）；`dingtalk_user_id` 恒非空。路径 `{user_ref}` / 参数 `manager_id` 接受裸 `user_id` 或 `dt:<钉钉userid>` 前缀。

目录条目返回 `email`、`mobile`、`employee_number`、`status` 和保留的
`active`。这些字段是员工敏感信息，仅能用于已批准的应用内选人、单据和身份映射；
不得写入日志、不得下发到不需要该数据的前端，也不得作为新的认证或授权事实。
用户条目不返回 `unionId`、`corp_id` 和完整主管链；
`corp_id` 只出现在 `directory_snapshot.snapshots[]` 作为多企业快照边界。

### `GET /api/v1/apps/{app_key}/directory/users`

搜索/分页列表。查询参数（全部可选，AND）：

| 参数 | 说明 |
| --- | --- |
| `q` | 对 `name` / `title` / `dingtalk_user_id` 大小写不敏感子串匹配；空串等同省略 |
| `department_id` | 该部门**直接成员**（不含子部门） |
| `manager_id` | 用户引用，过滤其**直接下属** |
| `include_inactive` | `"true"` 时包含 `disabled` / `departed` 以及从最新权威快照消失后保留的 tombstone；默认仅 `active` |
| `snapshot_id` | 可选的分页快照固定值；第一页省略，后续页应传回首页 `directory_snapshot.snapshot_id` |
| `page` / `page_size` | 默认 1/20；`page_size` 上限 **200** |

当请求传入的 `snapshot_id` 已不是当前快照，或快照在本次查询期间发生变化，
返回 `409 CONFLICT`，`details.reason` 为 `snapshot_mismatch` 或 `snapshot_changed`，
并附 `expected_snapshot_id` 与 `actual_snapshot_id`。消费方应从第一页重新读取，
不得把两个快照的页混合。

排序：`name` 升序，再 `dingtalk_user_id` 升序。

**成功响应（200）：**

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
    "snapshots": [
      {
        "source_slug": "dingtalk",
        "corp_id": "ding-corp-a",
        "generation": 42,
        "status": "success",
        "snapshot_at": "2026-07-16T10:00:00+08:00",
        "snapshot_at_status": "valid",
        "stale": false
      }
    ],
    "stale": false,
    "complete": true,
    "authoritative": true
  }
}
```

`status` 取 `active` / `disabled` / `departed`；`active` 等价于 `status == "active"`，
保留以便现有消费方使用布尔判断。从上游权威快照消失的员工不会被物理删除：
EasyAuth 保留其身份与联系字段，设置 `status: "departed"`、`active: false`，
并清空部门与主管关系。

### 目录快照元数据

所有目录成功响应都含 `directory_snapshot`：

- `snapshots` 按 `source_slug` / `corp_id` 稳定排序，一个企业一项；
- `generation` 是该企业上游快照世代，`status` 是同步状态；
- `snapshot_at` 是上游报告的快照时间，不参与新鲜度计算；
  `snapshot_at_status` 取 `valid` / `missing` / `invalid` / `future`；
- 单企业 `stale` 以 EasyAuth 本地成功事务提交时间判定，而不信任上游时钟；
- 顶层 `complete` 表示所有已知企业都有成功且非负的 generation；
  顶层 `stale` 表示任一快照过期或缺失；
  `authoritative` 仅在 `complete && !stale` 时为 `true`。

只有 `directory_snapshot.authoritative == true` 时，消费方才可将本次全量目录快照
用于离职/停用收敛；否则必须保留本地用户状态，不得把「本次未出现」
解释为离职。

### `GET /api/v1/apps/{app_key}/directory/users/{user_ref}`

详情：D1 条目字段 + `manager`（直接主管摘要；无主管时为 `null`）。
根对象同时含上文定义的 `directory_snapshot`（下例省略该通用块）。
引用不存在 → `404 NOT_FOUND`。

若用户已从权威目录消失，保留 tombstone 并返回 `status: "departed"`、
`active: false`、`departments: []`、`manager: null`。已 SSO 用户可用裸 `user_id`
查询；未 SSO 用户仍可用 `dt:` 引用查询。

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

### `GET /api/v1/apps/{app_key}/directory/users/{user_ref}/manager`

直接主管，响应为完整 D1 条目形状（含 `departments` 与 `avatar_url`）。

| 情形 | 响应 |
| --- | --- |
| `user_ref` 不存在 | `404 NOT_FOUND`，`details: {"reason": "user_not_found"}` |
| 用户存在但无主管 | `404 NOT_FOUND`，`details: {"reason": "no_manager"}` |

### `GET /api/v1/apps/{app_key}/directory/users/{user_ref}/subordinates`

仅直接下属（一层）、仅 active、全量不分页。排序同列表。`user_ref` 不存在 → `404`（`reason: "user_not_found"`）；存在但无下属 → `200` 空 `data`。

```json
{"data": []}
```

### `GET /api/v1/apps/{app_key}/directory/departments`

| 参数 | 说明 |
| --- | --- |
| `parent_id` | 可选。省略 → 全量扁平列表；传入 → 该部门的直接子部门 |

```json
{
  "data": [
    {"department_id": "1", "parent_id": "", "name": "杰发科技", "order": 0},
    {"department_id": "460001", "parent_id": "1", "name": "研发部", "order": 10}
  ]
}
```

根部门 `parent_id` 为空串；排序 `order` 升序再 `department_id` 升序；`parent_id` 不存在 → `200` 空 `data`。

### 目录限流

| 项 | 值 |
| --- | --- |
| 每凭据速率 | 240 次 / 60s（全部目录端点共享） |
| 认证失败 | 每 IP 30 次 / 300s |

超限返回 `429 THROTTLED`，带 `Retry-After` 头。

---

## 6. 通知

底层通道为钉钉工作通知 `asyncsend_v2`。应用的 `notify` 平台能力和当前
凭据的 `notify` 能力必须同时开启，否则返回 `403 PERMISSION_DENIED`
（文案：「应用未开通通知能力。」）。该 App 还必须在自己的 workspace 由
App owner 配置独立的、版本化钉钉通知通道；未配置时返回
`503 DEPENDENCY_UNAVAILABLE`。每条通知在受理时冻结通道版本，后续替换活动通道
不会改写已受理消息的发送身份。

**异步受理语义**：`POST` 成功仅代表 EasyAuth 已落库并排程投递；真正的逐人成败通过 `GET` 状态查询。收件人引用与目录一致：裸 `user_id` 或 `dt:<钉钉userid>`。仅允许通知 active 目录用户；解析失败的收件人不阻塞整体受理，直接记为终态 `failed`。

### `POST /api/v1/apps/{app_key}/notify/messages`

| 字段 | 必填 | 约束 |
| --- | --- | --- |
| `recipients` | 是 | 1~500 个用户引用；按解析后的钉钉 userid 合并去重 |
| `template` | 是 | `text` / `markdown` / `action_card` |
| `title` | markdown、action_card 必填 | ≤100 字符；text 忽略 |
| `content` | 是 | 组装后的钉钉 msg JSON ≤ **2048 字节（UTF-8）**，超限 `422` |
| `deeplink_url` | action_card 必填 | ≤500 字符；`https://` 或 `dingtalk://dingtalkclient/page/link?...`（内嵌 url 仍须 https） |
| `deeplink_title` | 否 | action_card 按钮文案，≤20 字符，默认「查看详情」 |
| `dedup_key` | 否 | ≤128 字符；app 内**永久**幂等键 |
| `biz_tag` | 否 | ≤64 字符，业务分类标签 |

**请求示例：**

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

**响应：**

| 情形 | HTTP | 说明 |
| --- | --- | --- |
| 新受理 | **202** | `accepted: true`；仅表示 EasyAuth 已落库并排程，不表示已调用钉钉或已发送 |
| `dedup_key` 命中且载荷一致 | **200** | `accepted: false`，`message_id` 为首次受理 ID |
| `dedup_key` 命中但载荷不同 | **409 CONFLICT** | — |
| 参数问题 | **422 VALIDATION_ERROR** | `details.field` 指明字段 |
| 速率/配额超限 | **429 THROTTLED** + `Retry-After` | 日配额的 Retry-After 到次日零点（Asia/Shanghai） |
| 凭据无效 | **401 AUTHENTICATION_FAILED** | 凭据问题，不应持续重试 |
| App / credential 未开通 `notify` | **403 PERMISSION_DENIED** | capability 配置问题，不应持续重试 |
| App 通知通道未配置 | **503 DEPENDENCY_UNAVAILABLE** | 运维配置问题；通道就绪前重试不会成功 |

```json
{
  "message_id": "0d9f5c1e-7a42-4b8e-9c3d-2f1a6b8e4d70",
  "accepted": true,
  "status": "pending",
  "recipient_total": 2,
  "recipient_rejected": 0
}
```

- `recipient_total`：解析合并后的收件人数（含受理时即失败者）
- `recipient_rejected`：受理时即判终态失败的收件人数（解析失败/非 active）

### `GET /api/v1/apps/{app_key}/notify/messages/{message_id}`

投递状态查询。`message_id` 不存在或属于其它 app → `404 NOT_FOUND`。

**成功响应（200）：**

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

**消息聚合 `status`：** `pending` / `sending` / `completed`（全部 sent 或 delivered）/ `partially_failed` / `failed`。

**收件人 `status`：** `pending` / `throttled` / `sent`（钉钉已受理，≠送达）/ `delivered` / `failed`。
其中 `sent` 是消费方可依赖的最低保证。`delivered` 仅表示钉钉明确的
send-result 回执把该 userid 分类进 `read_user_id_list` 或 `unread_user_id_list`；
它不表示已读，不得作为审批知悉、法务送达或其他合规事实。

**`error_code` 枚举：** `USER_NOT_FOUND`、`NO_DINGTALK_ID`、`USER_INACTIVE`、`DINGTALK_REJECTED`、`DINGTALK_DUPLICATE`、`DINGTALK_DAILY_LIMIT`、`EXHAUSTED`。

**状态时效：** `sent → delivered/failed` 依赖回执对账（约 60s 周期，
钉钉 send-result 查询窗口为 24h）。对账尽力而为；回执没有明确的
read/unread/失败名单归类时保持 `sent`，超过 24h 后也不推断为 `delivered`。

### 限流（通知）

| 项 | 默认 |
| --- | --- |
| POST 速率 | 60 次 / 60s（按 app，多凭据共享） |
| 每日收件人配额 | 5000 收件人·次 / 自然日（Asia/Shanghai） |
| GET 状态查询 | 240 次 / 60s（按凭据） |
| 认证失败 | 每 IP 30 次 / 300s |

超限返回 `429 THROTTLED`，带 `Retry-After` 头。

---

## 7. Webhook（EasyAuth → 下游）

审批完成等事件通过应用 webhook 配置投递，签名头包括：

- `X-EasyAuth-Event`
- `X-EasyAuth-Delivery`
- `X-EasyAuth-Timestamp`
- `X-EasyAuth-Signature`

具体签名算法与事件体见 SDK `verify_webhook` 与架构文档。webhook **配置/重投**在控制台私有 API，不在公共契约内。

---

## 8. SDK 对应方法

Python `EasyAuthAppClient`：

| 方法 | 接口 |
| --- | --- |
| `query_user_permissions` | GET permissions |
| `sync_manifest` | POST manifest-sync |
| `create_approval` | POST approval-instances |
| `list_approvals` | GET approval-instances |
| `get_approval` | GET approval-instances/{id} |
| `list_approval_templates` | GET approval-templates |
| `search_directory_users` | GET directory/users |
| `get_directory_user` | GET directory/users/{user_ref} |
| `get_directory_user_manager` | GET directory/users/{user_ref}/manager |
| `list_directory_user_subordinates` | GET directory/users/{user_ref}/subordinates |
| `list_directory_departments` | GET directory/departments |
| `send_notification` | POST notify/messages |
| `get_notification` | GET notify/messages/{message_id} |

SDK `0.3.0` 的 `EasyAuthClientError` 结构化暴露 `status_code`、`error_code`、
`details`、`retry_after`、`retry_after_seconds`、`retryable` 和 `transport_error`。
SDK 不自动重试；调用方应仅在 `retryable == true` 时按业务幂等边界重试，
其中 `429` 须遵守 `Retry-After`。
