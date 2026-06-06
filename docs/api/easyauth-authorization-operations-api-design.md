# EasyAuth 业务授权运营页面 API 设计

## 状态

设计草案，等待评审。

## 日期

2026-06-06

## 范围

本文定义 EasyAuth 管理控制台和员工门户使用的同源私有 API。它们用于业务授权运营增强，包括应用配置、权限模板、矩阵配置、凭据操作、联调测试、员工门户增强、运营看板和健康状态。

公共下游应用权限查询 API 不变：

```http
GET /api/v1/apps/{app_key}/users/{user_id}/permissions
Authorization: Bearer {app_token_or_oauth_access_token}
```

公共响应仍只包含 `user_id`、`app_key`、`roles`、`permissions`、`version` 和 `expires_at`。权限模板 group 不会出现在 `permissions` 中。

## API 边界

- 管理端 API 必须统一放在 `/console/api/v1/`。
- 员工门户增强 API 必须统一放在 `/portal/api/v1/`。
- 管理端 API 只供 EasyAuth 页面使用，不作为下游应用接入契约。
- 管理端 API 使用 Django session、CSRF 和 EasyAuth 管理权限。
- 员工门户 API 使用 Django session 和 CSRF，只能访问当前登录用户自己的资源。
- 管理端 API 不接受静态 app token 或 OAuth2 access token 作为管理身份。
- 所有列表接口必须分页。
- 所有写操作必须写入审计日志。
- 所有错误使用统一错误结构。

## 阶段化 API 落地计划

### 阶段 1（OPS-1）：配置完整性与接入联调 API

阶段目标：

- 支撑应用负责人从空 App 完成配置、权限模板导入、凭据准备和联调。
- 保持公共权限查询 API 不变，所有新增接口都限定在页面私有 API。

接口范围：

- `/console/api/v1/apps`
- `/console/api/v1/apps/{app_key}`
- `/console/api/v1/apps/{app_key}/configuration-status`
- `/console/api/v1/apps/{app_key}/memberships`
- `/console/api/v1/apps/{app_key}/permission-template-imports/*`
- `/console/api/v1/apps/{app_key}/permission-tree`
- `/console/api/v1/apps/{app_key}/permission-groups`
- `/console/api/v1/apps/{app_key}/roles`
- `/console/api/v1/apps/{app_key}/permissions`
- `/console/api/v1/apps/{app_key}/role-permission-matrix`
- `/console/api/v1/apps/{app_key}/approval-rules`
- `/console/api/v1/apps/{app_key}/credentials/*`
- `/console/api/v1/apps/{app_key}/permission-query-tests`
- `/console/api/v1/apps/{app_key}/integration-guide`

验收标准：

- 应用负责人只能访问自己负责 App 的接口。
- 模板预览不写入 Permission、PermissionGroup 或 PermissionTemplateVersion。
- 矩阵保存冲突返回 409。
- 凭据创建或轮换只在响应中一次性返回明文。
- 联调接口可以返回真实权限查询结果和错误解释。

约束：

- 阶段 1 不开放员工变更、撤销和续期 API。
- 阶段 1 不接受 app token 作为管理身份。
- 阶段 1 不提供 Authentik 或 DingTalk 配置接口。

验证方式：

- API 测试覆盖 session 鉴权、CSRF、AppMembership、分页、409 冲突和敏感字段脱敏。
- 浏览器冒烟覆盖从配置完整性 blocking 到联调成功。

### 阶段 2（OPS-2）：员工门户增强 API

阶段目标：

- 支撑员工查看自己的授权、申请状态和即将过期授权。
- 保持员工门户 API 与管理控制台 API 分离。

接口范围：

- `/portal/api/v1/me/grants`
- `/portal/api/v1/me/grants/expiring`
- `/portal/api/v1/me/access-requests`

验收标准：

- 当前用户只能读取自己的 grants 和 access requests。
- 提交申请只能为当前登录用户创建 AccessRequest。
- 响应能表达 `approved` 与 `grant_applied` 的差异。
- 即将过期接口默认只返回未来 14 天内到期授权。

约束：

- 阶段 2 不提供管理员操作。
- 阶段 2 不直接写 AccessGrant。
- 阶段 2 不展示或代理 Authentik Application Dashboard。

验证方式：

- API 测试覆盖越权访问、非 active 用户、可申请 Role 筛选和提交校验。
- 门户浏览器冒烟覆盖我的权限、我的申请和即将过期。

### 阶段 3（OPS-3）：运营看板与失败恢复 API

阶段目标：

- 支撑系统管理员定位和恢复授权闭环异常。
- 把失败恢复、紧急撤权和依赖健康纳入审计。

接口范围：

- `/console/api/v1/operations/access-requests`
- `/console/api/v1/operations/access-grants`
- `/console/api/v1/operations/access-requests/{request_id}/retry-grant`
- `/console/api/v1/operations/emergency-revokes`
- `/console/api/v1/operations/dependency-health`
- `/console/api/v1/audit-logs`

验收标准：

- `grant_failed` 重试对已处理申请保持幂等。
- 紧急撤权后公共权限查询返回空权限并体现最新 version。
- 健康状态不返回外部系统 secret。
- 审计查询按 actor、target、event type、App 和时间范围分页。

约束：

- 阶段 3 的重试和紧急撤权只允许系统管理员执行。
- 重试必须复用 `GrantService`。
- 健康接口只读，不配置 Authentik 或 DingTalk。

验证方式：

- API 测试覆盖可重试失败、不可重试失败、重复重试、紧急撤权和审计记录。
- 权限查询集成测试覆盖撤权后的下游 API 表现。

### 阶段 4（OPS-4）：变更、撤销和续期 API

阶段目标：

- 支撑员工自助发起角色变更、撤销和续期申请。
- 保持生命周期变更的审批、授权落库和审计边界。

接口范围：

- 扩展 `/portal/api/v1/me/access-requests` 支持 `request_type=change`、`revoke` 和 `renew`。
- 扩展 `/console/api/v1/operations/access-requests` 支持生命周期申请筛选。

验收标准：

- change 申请只影响目标 App。
- revoke 申请只能减少权限。
- renew 申请不能绕过最长授权期限。
- 审批通过后仍由 `GrantService` 写入最终授权事实。

约束：

- 阶段 4 不新增公共下游 API。
- 阶段 4 不允许员工为其他用户提交生命周期申请。
- DingTalk 仍只是流程通过证据。

验证方式：

- API 测试覆盖 request_type 校验、非法状态、重复审批回调和 version 变化。
- 端到端冒烟覆盖续期前后权限查询响应。

## 通用响应结构

列表响应：

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

错误响应：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数无效。",
    "details": {
      "field": "app_key"
    }
  }
}
```

状态码：

| 状态码 | 使用场景 |
| --- | --- |
| 400 | 请求格式或查询参数非法 |
| 401 | 未登录或 session 失效 |
| 403 | 当前用户无管理权限 |
| 404 | 管理资源不存在 |
| 409 | 状态冲突、重复导入或版本冲突 |
| 422 | 语义校验失败 |
| 500 | 内部错误，不暴露实现细节 |

## 应用与配置完整性

### 查询应用列表

```http
GET /console/api/v1/apps?page=1&page_size=20&status=active&owner_user_id=ak_uid_123
```

响应字段：

- `id`
- `app_key`
- `name`
- `is_active`
- `owners`
- `configuration_status`: `ready`、`warning`、`blocking`
- `updated_at`

权限：

- 系统管理员可查看全部 App。
- 应用负责人和开发者只能查看自己关联的 App。

### 查询应用详情

```http
GET /console/api/v1/apps/{app_key}
```

响应包含：

- App 基本信息。
- 负责人和开发者。
- Role、Permission 数量。
- active 凭据数量。
- 最近模板版本。
- 配置完整性摘要。

### 查询配置完整性

```http
GET /console/api/v1/apps/{app_key}/configuration-status
```

响应：

```json
{
  "app_key": "crm",
  "status": "blocking",
  "items": [
    {
      "level": "blocking",
      "code": "REQUESTABLE_ROLE_MISSING_APPROVAL_RULE",
      "message": "可申请角色缺少有效审批规则。",
      "target_type": "role",
      "target_id": "sales_manager"
    }
  ]
}
```

## 应用成员

### 查询应用成员

```http
GET /console/api/v1/apps/{app_key}/memberships
```

### 新增应用成员

```http
POST /console/api/v1/apps/{app_key}/memberships
Content-Type: application/json

{
  "user_id": "ak_uid_123",
  "role": "owner"
}
```

规则：

- 只有系统管理员可以新增或禁用 AppMembership。
- `role` 支持 `owner` 和 `developer`。
- 禁用成员使用 PATCH，不做物理删除。

### 禁用应用成员

```http
PATCH /console/api/v1/apps/{app_key}/memberships/{membership_id}
Content-Type: application/json

{
  "is_active": false
}
```

## 权限模板

### 预览模板导入

```http
POST /console/api/v1/apps/{app_key}/permission-template-imports/preview
Content-Type: application/json

{
  "format": "yaml",
  "content": "version: 1\ngroups: []\n"
}
```

响应：

```json
{
  "preview_id": "pti_20260606_001",
  "app_key": "crm",
  "summary": {
    "groups_to_create": 2,
    "groups_to_update": 1,
    "permissions_to_create": 3,
    "permissions_to_deprecate": 1
  },
  "changes": [
    {
      "change_type": "create_permission",
      "key": "ALLOW_PIPELINE_CREATE",
      "name": "创建流水线",
      "group_key": "PIPELINE_GROUP"
    }
  ],
  "blocking_errors": []
}
```

规则：

- 预览不写入 Permission、PermissionGroup 或 PermissionTemplateVersion。
- 预览结果只能写入短期缓存或专用 Preview 记录，不能作为已导入模板版本。
- 预览结果必须有过期时间，避免长期保存未确认模板。
- `content` 大小必须受限。

### 确认模板导入

```http
POST /console/api/v1/apps/{app_key}/permission-template-imports/{preview_id}/confirm
```

响应：

```json
{
  "template_version": 4,
  "status": "imported",
  "imported_at": "2026-06-06T10:15:00Z"
}
```

规则：

- 确认导入必须重新校验 preview 与当前数据版本，避免覆盖并发变更。
- 导入不能删除历史 Permission，只能 inactive 或 deprecated。
- 写入 `permission_template_imported` 审计事件。

### 查询模板版本

```http
GET /console/api/v1/apps/{app_key}/permission-template-versions?page=1&page_size=20
```

## 权限分组与权限目录

### 查询权限树

```http
GET /console/api/v1/apps/{app_key}/permission-tree
```

响应：

```json
{
  "app_key": "crm",
  "groups": [
    {
      "key": "PIPELINE_GROUP",
      "name": "流水线",
      "children": [
        {
          "key": "ALLOW_PIPELINE_CREATE",
          "name": "创建流水线",
          "type": "permission",
          "is_active": true,
          "deprecated_at": null
        }
      ]
    }
  ],
  "ungrouped_permissions": []
}
```

### 创建或更新分组

```http
POST /console/api/v1/apps/{app_key}/permission-groups
Content-Type: application/json

{
  "key": "PIPELINE_GROUP",
  "name": "流水线",
  "parent_key": null,
  "display_order": 10
}
```

```http
PATCH /console/api/v1/apps/{app_key}/permission-groups/{group_key}
Content-Type: application/json

{
  "name": "流水线管理",
  "parent_key": null,
  "display_order": 20,
  "is_active": true
}
```

规则：

- group key 在同一 App 下唯一。
- parent 必须属于同一 App。
- 最大深度为 5。
- 不能形成环。

## 角色、权限与矩阵

### 查询角色

```http
GET /console/api/v1/apps/{app_key}/roles?page=1&page_size=100&is_active=true
```

### 创建角色

```http
POST /console/api/v1/apps/{app_key}/roles
Content-Type: application/json

{
  "key": "sales_manager",
  "name": "销售经理",
  "description": "负责销售团队客户跟进",
  "is_active": true,
  "requestable": true
}
```

### 更新或禁用角色

```http
PATCH /console/api/v1/apps/{app_key}/roles/{role_key}
Content-Type: application/json

{
  "name": "销售经理",
  "description": "负责销售团队客户跟进",
  "is_active": false,
  "requestable": false
}
```

规则：

- `role_key` 在同一 App 下唯一。
- 禁用 Role 不会直接撤销既有 AccessGrant；授权事实变化仍必须通过申请、审批、撤权或 `GrantService`。
- requestable Role 必须存在 active ApprovalRule 才能进入可申请状态。

### 查询权限

```http
GET /console/api/v1/apps/{app_key}/permissions?page=1&page_size=100&is_active=true
```

### 创建权限

```http
POST /console/api/v1/apps/{app_key}/permissions
Content-Type: application/json

{
  "key": "customer:view:department",
  "name": "查看部门客户",
  "description": "查看本部门客户资料",
  "group_key": "CUSTOMER_GROUP",
  "is_active": true
}
```

### 更新、禁用或废弃权限

```http
PATCH /console/api/v1/apps/{app_key}/permissions/{permission_key}
Content-Type: application/json

{
  "name": "查看部门客户",
  "description": "查看本部门客户资料",
  "group_key": "CUSTOMER_GROUP",
  "is_active": false,
  "deprecated_reason": "改用 customer:view:team"
}
```

规则：

- `permission_key` 在同一 App 下唯一。
- `permission_key` 的业务含义不能被修改；含义变化时新增 key 并废弃旧 key。
- 禁用或废弃 Permission 不做物理删除，不破坏历史授权和审计。

### 查询 RolePermission 矩阵

```http
GET /console/api/v1/apps/{app_key}/role-permission-matrix
```

响应：

```json
{
  "app_key": "crm",
  "roles": [
    {
      "key": "sales_manager",
      "name": "销售经理",
      "is_active": true,
      "requestable": true
    }
  ],
  "permission_tree": [],
  "assignments": [
    {
      "role_key": "sales_manager",
      "permission_key": "customer:view:department"
    }
  ],
  "version": "8b7f3a0c9e..."
}
```

### 保存 RolePermission 矩阵差异

```http
PATCH /console/api/v1/apps/{app_key}/role-permission-matrix
Content-Type: application/json

{
  "base_version": "8b7f3a0c9e...",
  "add": [
    {
      "role_key": "sales_manager",
      "permission_key": "customer:edit:own"
    }
  ],
  "remove": [
    {
      "role_key": "sales_manager",
      "permission_key": "customer:delete:any"
    }
  ]
}
```

规则：

- 服务端必须重新校验 Role 和 Permission 都属于同一个 App。
- `base_version` 冲突返回 409。
- 保存后写入 `role_permission_matrix_changed` 审计事件。
- 该接口只改变 RolePermission，不直接改 AccessGrant。

## 审批规则

### 查询审批规则

```http
GET /console/api/v1/apps/{app_key}/approval-rules
```

### 创建审批规则

```http
POST /console/api/v1/apps/{app_key}/approval-rules
Content-Type: application/json

{
  "target_type": "role",
  "target_key": "sales_manager",
  "approver_userids": ["manager001"],
  "is_active": true
}
```

规则：

- 一条规则只能指向一个 role 或 permission。
- 目标必须属于同一个 App。
- `approver_userids` 必须是非空字符串数组。

### 更新或禁用审批规则

```http
PATCH /console/api/v1/apps/{app_key}/approval-rules/{approval_rule_id}
Content-Type: application/json

{
  "approver_userids": ["manager001", "manager002"],
  "is_active": false
}
```

规则：

- 禁用 ApprovalRule 后，对应 requestable Role 会在配置完整性中变为 blocking。
- 更新审批人不改变已经提交的 AccessRequest 审批实例。

## 凭据运营

### 查询凭据

```http
GET /console/api/v1/apps/{app_key}/credentials
```

响应只返回 metadata：

- `id`
- `credential_type`
- `name`
- `is_active`
- `created_at`
- `disabled_at`
- `last_used_at`

不得返回 token hash、明文 token、client secret 或 secret hash。

### 创建静态 app token

```http
POST /console/api/v1/apps/{app_key}/credentials/static-tokens
Content-Type: application/json

{
  "name": "crm-production"
}
```

响应：

```json
{
  "credential_id": 12,
  "plaintext_token": "eat_example",
  "display_once": true
}
```

### 轮换静态 app token

```http
POST /console/api/v1/apps/{app_key}/credentials/static-tokens/{credential_id}/rotate
```

规则：

- 返回新 token 明文一次。
- 旧 token 是否立即禁用由请求参数或页面确认控制。
- 审计 metadata 不记录明文 token。

### 禁用凭据

```http
POST /console/api/v1/apps/{app_key}/credentials/{credential_type}/{credential_id}/disable
Content-Type: application/json

{
  "reason": "凭据泄露排查"
}
```

### 创建 OAuth2 client credentials

```http
POST /console/api/v1/apps/{app_key}/credentials/oauth-clients
Content-Type: application/json

{
  "name": "crm-production"
}
```

响应只在本次返回 `client_secret` 明文。

## 联调测试

### 执行权限查询联调

```http
POST /console/api/v1/apps/{app_key}/permission-query-tests
Content-Type: application/json

{
  "user_id": "ak_uid_123",
  "credential_mode": "existing",
  "credential_type": "static_token",
  "credential_id": 12
}
```

可选一次性 token 模式：

```json
{
  "user_id": "ak_uid_123",
  "credential_mode": "one_time_token",
  "plaintext_token": "eat_example"
}
```

响应：

```json
{
  "http_status": 200,
  "result": {
    "user_id": "ak_uid_123",
    "app_key": "crm",
    "roles": ["sales_manager"],
    "permissions": ["customer:view:department"],
    "version": 12,
    "expires_at": "2026-06-06T10:20:00Z"
  },
  "explanation": "权限查询成功。"
}
```

规则：

- `one_time_token` 不落库。
- 审计只记录 `credential_mode`、credential metadata 和结果摘要。
- 禁用 App 或禁用凭据必须返回安全失败。

## 接入说明

### 查询接入说明

```http
GET /console/api/v1/apps/{app_key}/integration-guide
```

响应包含：

- app_key。
- 权限查询端点。
- 静态 app token 和 OAuth2 client credentials 使用方式。
- Authentik `sub` 作为 `user_id` 的说明。
- roles、permissions、version、expires_at 字段语义。
- 401、403、422、500 错误说明。
- 缓存和撤权 SLA。
- curl、Python 和 TypeScript 示例。
- 当前 Role、Permission 和权限模板版本摘要。

不得包含明文历史凭据。

## 员工门户增强 API

员工门户可以继续使用 Django SSR，也可以使用以下同源私有接口增强页面。

### 我的权限

```http
GET /portal/api/v1/me/grants?page=1&page_size=20
```

规则：

- 只返回当前登录用户自己的授权。
- 返回 active grant、roles、permissions、version、grant_type 和 grant_expires_at。

### 即将过期

```http
GET /portal/api/v1/me/grants/expiring?days=14
```

### 我的申请

```http
GET /portal/api/v1/me/access-requests?page=1&page_size=20
```

### 提交权限申请

```http
POST /portal/api/v1/me/access-requests
Content-Type: application/json

{
  "app_key": "crm",
  "role_keys": ["sales_manager"],
  "grant_type": "timed",
  "grant_expires_at": "2026-07-06T10:00:00Z",
  "reason": "需要处理客户跟进"
}
```

规则：

- 仍调用 `AccessRequestService`。
- 不直接创建 AccessGrant。
- 只允许申请 active、requestable 且有 active ApprovalRule 的 Role。
- 只能为当前登录用户提交申请，不能指定其他 requester。

## 运营看板

### 查询申请

```http
GET /console/api/v1/operations/access-requests?app_key=crm&status=grant_failed&page=1&page_size=20
```

### 查询授权

```http
GET /console/api/v1/operations/access-grants?app_key=crm&status=active&page=1&page_size=20
```

### 重试失败授权

```http
POST /console/api/v1/operations/access-requests/{request_id}/retry-grant
Content-Type: application/json

{
  "reason": "修复审批回调处理异常后重试"
}
```

规则：

- 只有系统管理员可以执行。
- 只能重试可重试的 `grant_failed`。
- 必须复用 `GrantService`。
- 已经 `grant_applied` 的请求不得再次递增 grant version。

### 紧急撤权

```http
POST /console/api/v1/operations/emergency-revokes
Content-Type: application/json

{
  "user_id": "ak_uid_123",
  "app_key": "crm",
  "reason": "安全事件应急"
}
```

规则：

- 只能减少权限。
- 必须记录原因。
- 必须复用 `GrantService`。
- 写入 `emergency_revoke_applied` 审计事件。

## 依赖健康

### 查询健康状态

```http
GET /console/api/v1/operations/dependency-health
```

响应：

```json
{
  "authentik": {
    "status": "healthy",
    "last_sync_at": "2026-06-06T10:00:00Z",
    "last_sync_result": "success"
  },
  "dingtalk": {
    "status": "warning",
    "last_callback_success_at": "2026-06-06T09:58:00Z",
    "recent_failure_count": 2
  },
  "celery": {
    "status": "healthy",
    "last_grant_expiration_run_at": "2026-06-06T10:05:00Z",
    "last_processed_count": 3
  }
}
```

规则：

- 只读。
- 不返回外部系统 secret。
- 不提供 Authentik 或 DingTalk 配置入口。

## 审计查询

```http
GET /console/api/v1/audit-logs?app_key=crm&event_type=permission_template_imported&page=1&page_size=20
```

规则：

- 应用负责人只能查看自己 App 的审计事件。
- 系统管理员可以全局查询。
- 审计日志不可修改、不可删除。

## 兼容性规则

- 任何新增公共下游 API 必须另行评审。
- `/api/v1/apps/{app_key}/users/{user_id}/permissions` 不因管理控制台能力变化而改变字段语义。
- 管理端 API 可以新增可选字段，但不能让页面依赖未记录的响应结构。
- 管理端 API 错误码和状态码必须稳定，便于页面显示一致中文解释。
