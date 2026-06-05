# 规格：EasyAuth MVP

## 状态

供评审的草稿。

本文档记录 EasyAuth 的 SPECIFY 阶段内容。它定义了 MVP 在进入技术规划和实现前必须验证的事项。

## 假设

1. EasyAuth 是单公司内部部署，而不是多租户 SaaS。
2. Authentik 是认证、身份生命周期和用户在职状态的来源。
3. DingTalk 用于审批流程，而不是最终的授权事实来源。
4. EasyAuth 是已连接内部应用的授权事实来源。
5. 内部应用通过统一 API 查询 EasyAuth，并且可以保留带有必要过期时间的本地权限缓存。
6. MVP 是一个 Web 应用：员工门户、管理控制台和 API。
7. MVP 首先针对基于角色的访问申请进行优化。只有在应用要求时才支持细粒度权限申请。

## 目标

使用 Authentik 和 DingTalk，为中小型公司构建一个由审批支撑的授权中心。

员工应能够登录、选择内部应用、申请角色或权限，并跟踪审批和授权状态。管理者通过 DingTalk 审批申请。审批通过后，EasyAuth 授予访问权限，内部应用查询 EasyAuth 以获取用户的角色和权限。

当一个内部应用能够在一天内接入 EasyAuth，并且随后停止实现自己的 DingTalk 审批、角色和权限逻辑时，MVP 即为成功。

## 用户

- 员工：为内部应用申请或变更访问权限。
- 审批人：在 DingTalk 中批准或拒绝访问申请。
- EasyAuth 管理员：注册应用、角色、权限、审批规则，并查看审计日志。
- 内部应用开发者：将应用接入 EasyAuth 的授权 API。

## 非目标

- 替代 Authentik 作为认证或身份生命周期系统。
- 替代 DingTalk 作为审批流程系统。
- 构建完整的 IAM 套件。
- 构建复杂的 ABAC 或策略引擎功能。
- 构建行级或字段级数据权限引擎。
- 构建 AI 权限推荐。
- 构建多租户 SaaS 部署、计费或租户隔离。
- 允许通过复制同事权限来绕过审批。
- 构建复杂的所有权交接转移流程。

## 产品定位

EasyAuth 首先不是用于访问申请的表单系统。它是面向内部应用的集中式授权层，并以员工自助服务和 DingTalk 审批作为访问流程。

核心产品承诺：

> 内部应用调用一个 EasyAuth API 来知道用户可以做什么。员工使用一个 EasyAuth 门户来申请访问权限。Authentik 提供身份状态。DingTalk 提供审批。EasyAuth 负责授权。

## 核心领域模型

### User

从 Authentik 同步的员工身份。

必填字段：

- `id`
- `authentik_user_id`
- `name`
- `email`
- `department`
- `status`
- `created_at`
- `updated_at`

允许的状态：

- `active`
- `disabled`
- `departed`

### App

连接到 EasyAuth 的内部应用。

必填字段：

- `id`
- `app_key`
- `name`
- `description`
- `status`
- `created_at`
- `updated_at`

允许的状态：

- `active`
- `disabled`

### Permission

一个应用下的细粒度操作或能力。

必填字段：

- `id`
- `app_id`
- `key`
- `name`
- `description`
- `created_at`
- `updated_at`

权限 key 示例：

- `customer:view:department`
- `customer:edit:own`
- `order:approve`

### Role

一个应用下可申请的一组权限。

必填字段：

- `id`
- `app_id`
- `key`
- `name`
- `description`
- `requestable`
- `created_at`
- `updated_at`

MVP 规则：员工主要申请角色，而不是单个权限。

### RolePermission

将权限映射到角色。

必填字段：

- `role_id`
- `permission_id`

### ApprovalRule

定义角色或权限申请必须由谁审批。

必填字段：

- `id`
- `app_id`
- `target_type`
- `target_id`
- `approver_source`
- `approver_config`
- `created_at`
- `updated_at`

允许的目标类型：

- `role`
- `permission`

MVP 规则：每个角色或权限都可以有自己的审批规则。如果某个角色没有审批规则，则在管理员配置审批规则之前，该角色不得被申请。

### AccessRequest

表示员工获取、变更或移除访问权限的申请。

必填字段：

- `id`
- `requester_user_id`
- `app_id`
- `request_type`
- `requested_role_ids`
- `requested_permission_ids`
- `status`
- `dingtalk_process_instance_id`
- `created_at`
- `updated_at`

允许的申请类型：

- `grant`
- `change`
- `revoke`

允许的状态：

- `draft`
- `submitted`
- `approval_pending`
- `approved`
- `rejected`
- `cancelled`
- `grant_applied`
- `grant_failed`

### AccessGrant

一个用户在一个应用中的当前授权状态。

必填字段：

- `id`
- `user_id`
- `app_id`
- `role_ids`
- `permission_ids`
- `source_request_id`
- `status`
- `version`
- `expires_at`
- `created_at`
- `updated_at`

允许的状态：

- `active`
- `revoked`

### AuditLog

重要授权操作的仅追加事件日志。

必填字段：

- `id`
- `actor_type`
- `actor_id`
- `event_type`
- `target_type`
- `target_id`
- `metadata`
- `created_at`

最少事件类型：

- `access_request_submitted`
- `approval_created`
- `approval_approved`
- `approval_rejected`
- `grant_created`
- `grant_changed`
- `grant_revoked`
- `user_departure_detected`
- `app_permission_queried`

## 必需用户故事

### 员工门户

- 作为员工，我可以通过 Authentik 登录。
- 作为员工，我可以看到可用于访问申请的内部应用。
- 作为员工，我可以选择一个应用并申请一个或多个角色。
- 作为员工，我可以将申请提交到 DingTalk 审批。
- 作为员工，我可以看到申请是待处理、已批准、已拒绝还是已应用。
- 作为员工，我可以申请变更现有访问权限。

### 管理控制台

- 作为管理员，我可以注册内部应用。
- 作为管理员，我可以配置应用的角色。
- 作为管理员，我可以配置应用的权限点。
- 作为管理员，我可以将权限映射到角色。
- 作为管理员，我可以为每个角色或权限配置审批规则。
- 作为管理员，我可以查看申请、审批、授权记录、变更、撤销和用户离职清理的审计日志。

### 内部应用接入

- 作为内部应用，我可以向 EasyAuth 的 API 进行认证。
- 作为内部应用，我可以查询某个用户在我的应用中的角色和权限。
- 作为内部应用，我会在每个响应中收到缓存过期时间。
- 作为内部应用，我不会直接调用 DingTalk 进行访问审批。
- 作为内部应用，我不会直接从 DingTalk 用户数据推断授权。

## 必需流程

### 访问申请流程

1. 员工通过 Authentik 登录。
2. 员工打开 EasyAuth 的员工门户。
3. EasyAuth 列出可申请的应用。
4. 员工选择一个应用。
5. EasyAuth 列出该应用可申请的角色。
6. 员工选择角色并提交申请。
7. EasyAuth 创建一个 `AccessRequest`。
8. EasyAuth 创建一个 DingTalk 审批实例。
9. EasyAuth 将申请标记为 `approval_pending`。
10. DingTalk 发送审批回调。
11. EasyAuth 验证并记录该回调。
12. 如果已批准，EasyAuth 创建或更新 `AccessGrant`。
13. EasyAuth 写入审计日志事件。
14. 员工看到最终的已应用状态。

### 权限查询流程

1. 内部应用使用应用凭据调用 EasyAuth API。
2. EasyAuth 认证该应用。
3. EasyAuth 验证该应用只能查询自己的权限。
4. EasyAuth 查找目标用户以及该应用的有效授权记录。
5. EasyAuth 返回角色、权限 key、授权记录版本和缓存过期时间。
6. 内部应用缓存响应直到 `expires_at`。

### 离职清理流程

1. Authentik 将用户标记为 disabled 或 departed。
2. EasyAuth 接收或检测到该状态变更。
3. EasyAuth 撤销该用户的所有有效授权记录。
4. EasyAuth 递增受影响的授权记录版本。
5. EasyAuth 写入审计日志事件。
6. 之后的权限查询不会返回有效角色或权限。

### 访问变更流程

1. 员工打开某个应用的当前访问权限。
2. 员工选择目标角色集合。
3. EasyAuth 创建变更申请。
4. EasyAuth 根据所申请的角色或权限发送 DingTalk 审批。
5. 审批通过后，EasyAuth 更新授权记录。
6. EasyAuth 写入审计日志事件。

## API 契约

### 查询用户权限

```http
GET /api/v1/apps/{app_key}/users/{user_id}/permissions
Authorization: Bearer {app_token}
```

必需行为：

- token 必须识别调用方应用。
- 调用方应用只能查询自己的 `app_key`。
- 已禁用的应用不能查询权限。
- 已禁用或已离职用户不会返回有效角色或权限。
- 响应必须包含缓存过期时间。
- 响应必须包含单调递增的授权记录版本。

成功响应：

```json
{
  "user_id": "u_123",
  "app_key": "crm",
  "roles": ["sales_manager"],
  "permissions": [
    "customer:view:department",
    "customer:edit:own"
  ],
  "version": 12,
  "expires_at": "2026-06-05T10:15:00Z"
}
```

无有效访问权限响应：

```json
{
  "user_id": "u_123",
  "app_key": "crm",
  "roles": [],
  "permissions": [],
  "version": 13,
  "expires_at": "2026-06-05T10:15:00Z"
}
```

## 缓存规则

- EasyAuth 必须在每次成功的权限查询中返回 `expires_at`。
- 内部应用只能将权限响应缓存到 `expires_at`。
- 初始 MVP 的缓存 TTL 应可按应用配置。
- 建议默认 TTL：5 分钟。
- 建议最大 TTL：15 分钟。
- 任何授权记录创建、变更或撤销都必须递增受影响的授权记录版本。

## DingTalk 审批要求

- EasyAuth 必须在申请提交时创建一个 DingTalk 审批实例。
- EasyAuth 必须存储 DingTalk 流程实例 ID。
- DingTalk 回调必须是幂等的。
- 重复回调不得创建重复授权记录。
- 被拒绝的审批不得创建或变更授权记录。
- 审批通过后，如果授权记录应用失败，必须让申请保持在 `grant_failed` 状态，并产生一个审计日志事件。

## Authentik 接入要求

- Authentik 是用户登录的身份来源。
- Authentik 是已禁用或已离职用户状态的来源。
- EasyAuth 不得将 DingTalk 用户存在视为在职证明。
- 当 Authentik 将用户标记为 disabled 或 departed 时，EasyAuth 必须撤销该用户的所有有效授权记录。

## 命令

实现技术栈尚未选择。这些命令必须在技术计划中最终确定。

预期命令类别：

```bash
# Development server
TBD

# Build
TBD

# Unit and integration tests
TBD

# Lint and formatting
TBD

# Type checking
TBD
```

## 项目结构

实现技术栈尚未选择。建议的仓库结构：

```text
docs/
  specs/
    easyauth-mvp.md
src/
  employee-portal/
  admin-console/
  api/
  auth/
  integrations/
    authentik/
    dingtalk/
  authorization/
  audit/
tests/
  unit/
  integration/
  e2e/
```

## 代码风格

实现技术栈尚未选择。代码风格必须在选择后端和前端技术栈后最终确定。

不论技术栈如何，都需要遵守的约定：

- 使用明确的领域名称：`AccessGrant`、`AccessRequest`、`ApprovalRule`。
- 将认证和授权概念分开。
- 将外部回调视为不可信输入。
- 优先使用带类型的请求和响应契约。
- 除非必要，否则避免在公共 API 响应中暴露内部数据库 ID。

API 响应契约示例：

```ts
type PermissionQueryResponse = {
  user_id: string;
  app_key: string;
  roles: string[];
  permissions: string[];
  version: number;
  expires_at: string;
};
```

## 测试策略

测试必须覆盖：

- 访问申请状态转换。
- DingTalk 回调幂等性。
- 审批拒绝行为。
- 审批通过后的授权记录创建。
- 权限查询 API 认证。
- 应用隔离：一个应用不能查询另一个应用的权限。
- 缓存 TTL 和版本行为。
- Authentik 已禁用/已离职用户清理。
- 核心事件的审计日志创建。

最低测试层级：

- 领域状态转换的单元测试。
- API 契约的集成测试。
- 模拟 DingTalk 回调的集成测试。
- 模拟 Authentik 用户状态变更的集成测试。
- 从申请到查询完整流程的端到端冒烟测试。

## 边界

### 始终

- 保持 EasyAuth 作为授权事实来源。
- 要求内部应用权限查询必须进行 API 认证。
- 为申请、审批、授权记录、变更、撤销和离职清理事件写入审计日志。
- 幂等处理外部回调。
- 在权限查询响应中返回缓存过期时间。
- 当 Authentik 将用户标记为 disabled 或 departed 时，撤销所有有效授权记录。

### 先询问

- 将身份来源从 Authentik 更改为其他系统。
- 将审批提供方从 DingTalk 更改为其他系统。
- 让 EasyAuth 支持多租户。
- 添加 ABAC、策略引擎、行级权限或字段级权限。
- 允许未经审批创建访问授权记录。
- 允许通过权限复制或转移绕过审批。
- 选择实现技术栈。

### 永不

- 将 DingTalk 视为最终授权来源。
- 将 DingTalk 视为权威的在职状态来源。
- 允许内部应用在没有应用认证的情况下查询权限。
- 允许一个应用查询另一个应用的权限。
- 因重复审批回调创建重复授权记录。
- 静默忽略失败的审批回调或失败的授权记录应用。
- 删除安全敏感事件的审计历史。

## 成功标准

当本规格完成评审并且开放问题得到解决时，MVP 即可进入技术规划。

当以下条件全部为真时，MVP 即可用于试点：

- 员工可以通过 EasyAuth 为一个内部应用申请访问权限。
- EasyAuth 为该申请创建 DingTalk 审批实例。
- DingTalk 审批回调正确更新申请状态。
- 审批成功会创建或更新有效访问授权记录。
- 审批拒绝不会创建或变更访问授权记录。
- 内部应用可以查询 EasyAuth 以获取用户的角色和权限。
- 权限查询响应包含 `roles`、`permissions`、`version` 和 `expires_at`。
- 应用凭据可阻止跨应用权限查询。
- Authentik 已禁用或已离职状态会撤销该用户的所有有效授权记录。
- 申请、审批、授权、变更和撤销事件都有审计日志。
- 一个试点应用可以在一个工作日内完成接入。

## 开放问题

1. EasyAuth 应使用哪种实现技术栈？
2. 员工门户和管理控制台应该是一个带有基于角色导航的 Web 应用，还是两个独立应用？
3. 应用 API 凭据在 MVP 中应使用静态 token、OAuth2 client credentials，还是签名请求？
4. 应用 API 中的 `user_id` 应该是 EasyAuth 的内部用户 ID、Authentik ID、邮箱，还是员工编号？
5. EasyAuth 应如何接收 Authentik 用户状态变更：webhook、定时同步，还是两者都用？
6. 第一个试点应使用哪个 DingTalk 审批模板？
7. 在已连接应用中，权限撤销生效的最大可接受时间是多少？
8. 授权记录是否应自动过期，还是在变更、撤销或离职之前一直有效？
9. 管理员在 MVP 中是否需要手动紧急撤销？
10. 哪个试点应用将验证一天接入目标？
