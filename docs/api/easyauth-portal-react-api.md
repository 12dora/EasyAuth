# EasyAuth 员工门户 React 私有 API

## 范围

本页记录员工门户 React 页面使用的同源私有 API。路径统一前缀：`/portal/api/v1/`。

**鉴权：**

- 依赖 Django session 中的 `AUTHENTIK_SESSION_KEY`
- 绑定的 `UserMirror` 必须为 `active`
- 未登录或用户失效 → `401 AUTHENTICATION_FAILED`（「员工门户登录已失效。」）
- **不接受**请求体传入 requester 身份，**不接受**应用 Bearer token

**边界：**

- 本接口仅供门户前端使用，**不是**下游应用公共契约
- 下游权限查询请使用 [`easyauth-public-api.md`](./easyauth-public-api.md)

**统一错误结构：** 与公共 API 相同的 `{ "error": { "code", "message", "details" } }`。

**列表分页通用形态：**

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 0,
    "total_pages": 0
  }
}
```

`page` 与 `page_size` 只有省略或空值时使用默认值；出现非整数、非正数或超过上限的值必须返回
`422 VALIDATION_ERROR`。前端不得把畸形 2xx 列表信封转换为空列表。

查询参数：`page`（默认 1）、`page_size`（默认 20，最大 100）。

---

## GET /portal/api/v1/me/grants

当前登录员工的有效授权列表（分页）。

目录解析不可用时返回 `503 DEPENDENCY_UNAVAILABLE`。

单条授权会返回 `grant_id` 与 `grant_revision`。门户发起 `change`、`revoke`、`renew`
时必须把这两个值原样作为 `base_grant_id` 与 `base_grant_revision` 提交，用来固定申请基于的
授权修订。

---

## GET /portal/api/v1/me/grants/expiring

即将到期的授权列表。

**查询参数：**

| 参数 | 说明 |
| --- | --- |
| `days` | 到期窗口天数，默认 14，范围 1–90 |
| `page` / `page_size` | 分页 |

---

## GET /portal/api/v1/me/access-requests

当前员工提交过的授权申请列表（分页）。

**单条字段（摘要）：**

```json
{
  "id": 1,
  "app_key": "crm",
  "app_name": "CRM",
  "request_type": "grant",
  "base_grant_id": null,
  "base_grant_revision": null,
  "status": "submitted",
  "status_label": "等待审批",
  "grant_type": "permanent",
  "grant_expires_at": null,
  "reason": "…",
  "submitted_at": "…",
  "authorization_groups": [
    {"key": "auditor", "kind": "role", "name": "审计员"}
  ],
  "direct_grants": [
    {"permission": "order.view", "permission_name": "查看订单", "scope": "SELF"}
  ],
  "decided_at": null,
  "decision_comment": ""
}
```

**状态枚举：** `submitted` / `approved` / `rejected` / `grant_applied` / `grant_failed` / `grant_conflict` / `grant_expired` / `withdrawn`。

`grant_conflict` 表示生命周期申请基于的基础授权修订已经变化。该状态不是可重试落库失败，前端必须提示申请人重新提交申请。

---

## POST /portal/api/v1/me/access-requests

提交授权申请。

**请求头：** `Idempotency-Key` 必填（非空，≤128 字符）。

**请求体：**

```json
{
  "app_key": "crm",
  "authorization_group_keys": ["auditor"],
  "direct_grants": [
    {"permission": "order.view", "scope": "SELF"}
  ],
  "approver_user_ids": ["ak-manager-1"],
  "request_type": "grant",
  "base_grant_id": null,
  "base_grant_revision": null,
  "grant_type": "timed",
  "grant_expires_at": "2026-12-31T00:00:00+00:00",
  "reason": "项目需要"
}
```

说明：

- 目标使用 **`authorization_groups`（授权组）**，不是历史文档中的 `roles`
- `request_type`：`grant` / `change` / `revoke` / `renew`
- `grant` 申请必须让 `base_grant_id` 与 `base_grant_revision` 为 `null` 或省略；`change`、`revoke`、`renew` 必须填写当前授权列表返回的 `grant_id` 与 `grant_revision`
- `grant_type`：`permanent` 或 `timed`（timed 必须带 `grant_expires_at`）
- `change`、`revoke`、`renew` 的基础授权主键与修订会进入幂等摘要；审批落地时若该授权修订已变化，申请进入 `grant_conflict`，不会改用最新授权事实
- 提交时会冻结授权组展开后的权限与 scope 快照，并记录提交时的 `authorization_group_id_snapshot` 作为稳定历史值；审批列表、审批详情、审计元数据和授权落地前置事实必须使用同一份快照，后续授权组配置变化不会改变已提交申请的展示或执行事实

**成功：** `201`，`{ "access_request": { … } }`  
**冲突：** 同一幂等键不同 payload → `409`  
**校验失败：** `422 SEMANTIC_VALIDATION_ERROR` / `VALIDATION_ERROR`

---

## POST /portal/api/v1/me/access-requests/{request_id}/withdraw

申请人撤回**本人**、状态为 `submitted` 的申请。

| 场景 | HTTP |
| --- | --- |
| 首次撤回成功 | 200，`status=withdrawn` |
| 已是 `withdrawn` | 200 幂等，同一 item，不重复审计 |
| 非本人或不存在 | 404 |
| 其他终态（已审批/已拒绝等） | 409 |
| 未登录 | 401 |

**成功响应：**

```json
{
  "access_request": {
    "id": 1,
    "status": "withdrawn",
    "status_label": "已撤回"
  }
}
```

审计事件：`access_request_withdrawn`（仅首次撤回写入）。

---

## GET /portal/api/v1/me/approvals

当前用户作为审批人的待办/已办列表。

**查询参数：**

| 参数 | 说明 |
| --- | --- |
| `status` | `pending`（默认，`submitted` 且本人是审批人）或 `processed`（本人已决定） |
| `page` / `page_size` | 分页 |

审批条目在 access_request 基础上额外包含：

- `authorization_groups`（含提交时冻结的 grants 明细）
- `applicant`：`{ user_id, name, email, department }`
- `approver_user_ids`
- `decided_by` / `decided_at`

---

## GET /portal/api/v1/me/approvals/{request_id}

审批详情。仅审批人或已决定人可见；否则 404。

---

## POST /portal/api/v1/me/approvals/{request_id}/approve

站内通过。

**请求体（可选）：**

```json
{ "comment": "同意" }
```

非审批人 → `403`；已处理冲突 → `409`；授权落库失败 → `422`（可能带 `decision_committed`）。

如果审批决定已提交，但授权落地发现基础授权修订变化或申请已过期，接口返回 `409 CONFLICT`，错误明细带：

```json
{
  "error": {
    "code": "CONFLICT",
    "message": "基础授权已变化, 请重新提交申请。",
    "details": {
      "reason": "base_grant_revision_conflict",
      "decision_committed": true,
      "status": "grant_conflict",
      "request_id": 1
    }
  }
}
```

`details.reason` 取值为 `base_grant_revision_conflict` 或 `request_expired` 时，前端必须刷新审批列表并提示重新提交申请。该类冲突不得当作 `grant_failed` 重试。

---

## POST /portal/api/v1/me/approvals/{request_id}/reject

站内驳回。**`comment` 必填。**

```json
{ "comment": "范围过大" }
```

---

## GET /portal/api/v1/request-catalog

员工提交申请时可选的目录。

**成功响应结构：**

```json
{
  "apps": [
    {
      "id": 1,
      "app_key": "crm",
      "name": "CRM",
      "description": "…",
      "catalog_version": 3,
      "default_approver_user_ids": ["ak-owner-1"],
      "approver_resolution_status": "default_policy"
    }
  ],
  "authorization_groups": [
    {
      "key": "auditor",
      "kind": "role",
      "name": "审计员",
      "app_key": "crm",
      "…"
    }
  ],
  "permission_groups": [],
  "ungrouped_permissions": [],
  "approver_options": [
    {"user_id": "ak-manager-1", "name": "…", "…": "…"}
  ]
}
```

筛选规则：

- `apps`：active 应用
- **`authorization_groups`**：所属 App active、自身 active、`requestable=true`，且存在 active 审批规则
- 不再使用历史 `roles` 模型命名；前端与文档均以 `authorization_groups` 为准
- 可申请的直接权限见 `permission_groups` / `ungrouped_permissions`

---

## 兼容性

- 公共权限查询契约不变：`GET /api/v1/apps/{app_key}/users/{user_id}/permissions`
- 历史文档中的 `roles` 字段已废弃，统一为 `authorization_groups`
