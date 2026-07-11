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

## 5. Webhook（EasyAuth → 下游）

审批完成等事件通过应用 webhook 配置投递，签名头包括：

- `X-EasyAuth-Event`
- `X-EasyAuth-Delivery`
- `X-EasyAuth-Timestamp`
- `X-EasyAuth-Signature`

具体签名算法与事件体见 SDK `verify_webhook` 与架构文档。webhook **配置/重投**在控制台私有 API，不在公共契约内。

---

## 6. SDK 对应方法

Python `EasyAuthAppClient`：

| 方法 | 接口 |
| --- | --- |
| `query_user_permissions` | GET permissions |
| `sync_manifest` | POST manifest-sync |
| `create_approval` | POST approval-instances |
| `list_approvals` | GET approval-instances |
| `get_approval` | GET approval-instances/{id} |
| `list_approval_templates` | GET approval-templates |
