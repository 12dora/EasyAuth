# EasyAuth MVP 方案 v2

## 状态

基于用户反馈形成的决策草案。本文档在实现方向上取代第一版技术规划草案，但仍保留尚未确定的运营配置细节。

## 已确认决策

- 员工门户和管理控制台是一个具备角色感知能力的 Web 应用。
- 内部应用凭据同时支持静态 app token 和 OAuth2 client credentials。
- Authentik 状态更新同时使用 webhook 风格通知和定时同步。
- 授权记录创建时必须选择有限有效期或永久有效。
- 除非标记为试点配置输入，其余选择均在本方案中决定。

## 选定技术栈

- 运行时：Python 3.13。
- Web 应用：Django 5.2 LTS。
- API：Django REST Framework。
- 内部应用 OAuth2 provider：Django OAuth Toolkit。
- Authentik 登录客户端：Authlib OAuth/OIDC client for Django。
- 数据库：PostgreSQL 16+。
- 后台任务：Celery 5.6，Redis 作为 broker。
- 前端：Django 服务端渲染模板，并使用 HTMX 提供局部交互。
- 测试：pytest、pytest-django、responses 或 respx 用于 mock 外部 HTTP，Playwright 用于端到端 smoke 路径。
- 质量门槛：ruff、basedpyright、Django checks、migrations check、pytest 和 Playwright smoke。

选择理由：

- Django 5.2 是 LTS 版本，支持期延伸到 2028 年 4 月，比追逐最新功能版本更适合内部授权系统的长期维护。
- Django Admin 能加速早期试点应用配置，不必先构建完整自定义管理控制台。
- Django OAuth Toolkit 支持 OAuth2 provider 能力和 client credentials，符合 token + OAuth 的要求。
- 服务端渲染 UI 能让单应用 MVP 更小，同时仍允许员工和管理员路由共享布局、session、Authentik 登录和审计上下文。

## 身份与 DingTalk 资料结论

### DingTalk 可以提供什么

基于 DingTalk 文档：

- DingTalk 用户委托访问遵循 OAuth2 authorization-code flow。
- 使用 `scope=openid` 时，应用可以获取用户 access token，然后调用用户通讯录 profile API。
- 使用 `scope=openid corpid` 时，token 交换还可以返回用户选择的组织 ID。
- DingTalk 用户通讯录/profile API 可以暴露 `unionId`、`openId`、昵称、头像、手机号、邮箱和电话国家码等字段，具体取决于已授予的 scope 和权限。
- DingTalk 用户详情 API 可以暴露更丰富的组织字段，例如 `userid`、`unionid`、姓名、manager userid、手机号、工号、职位、邮箱、部门 ID、active 标记、管理员标记和角色列表，具体取决于应用权限。
- DingTalk 可以提供审批流程实例 ID 和审批实例生命周期 API，但它不是 EasyAuth 的授权事实来源。

### Authentik 可以接收和存储什么

基于 Authentik 文档：

- Authentik OAuth Source 可以在认证后调用 Profile URL，并在 source property mapping 中接收 OAuth claim 数据 `info`，以及 `client` 和 `token`。
- Source property mapping 可以把来源数据导入 Authentik 用户字段和用户 attributes。
- Authentik user 对象字段包括 `username`、`email`、只读 `uid`、显示用 `name`、`is_active` 和动态 `attributes`。

### 集成决策

EasyAuth 不把 DingTalk 当作身份来源或在职状态来源。

v2 身份模型如下：

- Authentik 仍然是登录身份和 active/disabled 状态的来源。
- EasyAuth 使用 Authentik OIDC 进行员工登录。
- EasyAuth 将 Authentik `uid` 存储为 `authentik_user_id`。
- EasyAuth 公共 API 的 `user_id` 表示 Authentik user subject/UID，而不是 EasyAuth 内部数据库 ID。
- DingTalk `unionId`、组织范围内的 `userid`、`corpId`、手机号、邮箱、工号、部门 ID 和 manager userid 是可选身份属性，会同步到 Authentik，并只为了审批路由、展示和审计上下文镜像到 EasyAuth。
- 邮箱、手机号和工号不是规范授权标识符，因为它们可能变化，并且可能具有个人敏感性。

如果试点环境中 Authentik 到 DingTalk 的直接 OAuth Source 映射与 DingTalk profile 响应形态不兼容，则增加一个 EasyAuth 持有的轻量 DingTalk profile bridge endpoint，向 Authentik 返回 OIDC 兼容 JSON。该 bridge 不得授予 EasyAuth 权限，也不得绕过 Authentik 作为身份权威来源。

## 授权 API 决策

权限查询保持为：

```http
GET /api/v1/apps/{app_key}/users/{user_id}/permissions
Authorization: Bearer {app_token_or_oauth_access_token}
```

规则：

- `user_id` 是 Authentik UID/OIDC subject。
- 调用方凭据精确映射到一个 EasyAuth `App`。
- 路径中的 `app_key` 必须匹配凭据绑定的应用。
- 静态 app token 以 hash 形式存储、可轮换、限定到一个应用，面向试点/bootstrap 和简单内部应用。
- OAuth2 client credentials 是长期推荐的集成方式。
- OAuth2 `/oauth/token` client-credentials flow 签发绑定到一个应用的短期 bearer token。
- 两种凭据类型必须产生相同的授权结果和审计行为。

响应：

```json
{
  "user_id": "ak_uid_123",
  "app_key": "crm",
  "roles": ["sales_manager"],
  "permissions": ["customer:view:department", "customer:edit:own"],
  "version": 12,
  "expires_at": "2026-06-05T10:15:00Z"
}
```

该 API 响应中的 `expires_at` 表示缓存过期时间，不表示授权记录有效期。

## 授权记录有效期决策

为避免混淆缓存过期时间和授权记录生命周期：

- 使用 `grant_lifetime_type` 存储授权记录生命周期，允许值为 `permanent` 或 `timed`。
- 当生命周期类型为 `timed` 时，存储 `grant_expires_at`。
- 对永久授权记录，`grant_expires_at` 为 null，`grant_lifetime_type` 为 `permanent`。
- 权限查询会过滤掉超过 `grant_expires_at` 的 timed 授权记录。
- 每次授权记录创建、变更、过期或撤销，都必须递增授权记录版本并写入审计日志。

原始规格中的 `AccessGrant.expires_at` 应实现为 `grant_expires_at`；API 缓存过期时间仍使用响应字段 `expires_at`。

## 缓存与撤权决策

- 默认应用权限缓存 TTL：5 分钟。
- 最大应用权限缓存 TTL：15 分钟。
- 高风险应用可以配置低至 60 秒。
- MVP 撤权 SLA 目标：默认情况下，已连接应用在 5 分钟内停止使用已撤销权限。
- MVP 包含管理员紧急撤权，但紧急撤权只能减少访问权限。它不能授予访问权限，也不能绕过审批。

## DingTalk 审批决策

试点审批使用名为 `EasyAuth Access Request` 的 DingTalk OA 审批模板。

必需模板字段：

- EasyAuth request ID。
- 申请人姓名和 Authentik user ID。
- 可用时包含 DingTalk `userid` 和 `unionId`。
- App name 和 app key。
- Requested roles 和 permissions。
- Request type：grant、change 或 revoke。
- Grant validity：permanent 或 timed。
- timed 授权记录的 Grant expiry date。
- Request reason。

审批行为：

- EasyAuth 创建 DingTalk 审批实例，并保存返回的 process instance ID。
- DingTalk callback payload 作为不可信外部输入处理。
- 重复 callback 必须幂等，不能创建重复授权记录。
- 拒绝审批永远不能创建或变更授权记录。
- 审批成功后，只能在 EasyAuth 内创建或更新授权记录。

## Authentik 同步决策

同时使用两种机制：

- Webhook 路径：Authentik notification transport 将相关用户生命周期事件发送到 EasyAuth。
- 定时路径：EasyAuth 定期拉取 Authentik 用户，并对 `is_active`、email、name 和选定 attributes 进行对账。

规则：

- Webhook 加速清理，但不是唯一来源。
- 定时同步是最终一致性的兜底机制。
- 如果 Authentik 将用户标记为 inactive 或 disabled，EasyAuth 会撤销该用户所有活跃授权记录、递增版本并写入审计事件。
- 如果 Authentik 表示用户 inactive，则 DingTalk 用户存在或 DingTalk active 状态都不足以维持授权记录 active。

## 试点应用决策

试点应用：CRM。

理由：

- MVP 规格中已经使用 CRM 风格示例，例如 `customer:view:department` 和 `customer:edit:own`。
- CRM 授权可以用一组小而真实的角色集轻松验证。

试点角色：

- `sales_rep`
- `sales_manager`
- `finance_viewer`

试点权限：

- `customer:view:own`
- `customer:view:department`
- `customer:edit:own`
- `order:approve`
- `invoice:view`

## 实施任务

### 任务 1：搭建 Django 单体应用

**说明：** 创建 Django 项目、标准命令、数据库设置、静态资源流水线和测试框架。

**验收标准：**
- [ ] `manage.py` 项目可以在本地运行。
- [ ] 存在基于 PostgreSQL 的本地开发设置。
- [ ] 已记录 dev、test、lint、typecheck、format、migrations 和 worker 的标准命令。
- [ ] Django Admin 已启用。

**验证：**
- [ ] `python manage.py check`
- [ ] `python manage.py migrate --check`
- [ ] `pytest`

**依赖：** 无

**预估范围：** M

### 任务 2：实现核心领域模型

**说明：** 添加 User mirror、App、Permission、Role、RolePermission、ApprovalRule、AccessRequest、AccessGrant、AppCredential、OAuth app binding 和 AuditLog 模型。

**验收标准：**
- [ ] App、role、permission 和 approval rule 的唯一约束可以防止重复配置。
- [ ] AccessGrant 支持 `grant_lifetime_type` 和 `grant_expires_at`。
- [ ] AuditLog 在应用层是 append-only。
- [ ] 静态 app token 只以 hash 形式存储。

**验证：**
- [ ] 模型测试覆盖唯一约束、授权记录生命周期和 token hashing。
- [ ] 迁移可以从空数据库干净应用。

**依赖：** 任务 1

**预估范围：** M

### 任务 3：优先构建权限查询契约

**说明：** 在 UI 和 DingTalk 集成之前，基于种子用户和授权记录实现权限查询 endpoint。

**验收标准：**
- [ ] 静态 token 认证可用。
- [ ] OAuth2 client credentials 认证可用。
- [ ] 一个凭据只能查询其绑定的 `app_key`。
- [ ] API 响应包含 roles、permissions、version 和缓存 `expires_at`。
- [ ] inactive Authentik 用户以及已过期/已撤销的授权记录返回无活跃 roles 或 permissions。

**验证：**
- [ ] API 测试覆盖静态 token 成功、OAuth 成功、缺失凭据、无效凭据、跨应用拒绝、过期授权记录、已撤销授权记录和 inactive 用户。

**依赖：** 任务 2

**预估范围：** M

### 任务 4：添加 Authentik 登录和用户同步

**说明：** 将员工登录接入 Authentik OIDC，并通过 webhook 和定时同步同时同步 Authentik 用户状态。

**验收标准：**
- [ ] 登录会基于 Authentik claims 创建或更新 EasyAuth user mirror。
- [ ] Authentik UID 是 EasyAuth 公共 `user_id` 的规范来源。
- [ ] Authentik webhook endpoint 接受签名或 token 认证的生命周期通知。
- [ ] 定时同步会对账 Authentik `is_active` 和已映射 attributes。
- [ ] inactive 用户会触发授权记录撤销。

**验证：**
- [ ] Mock Authentik OIDC 登录测试。
- [ ] Webhook 撤权测试。
- [ ] 定时同步撤权测试。

**依赖：** 任务 2-3

**预估范围：** M

### 任务 5：配置 CRM 试点应用

**说明：** 使用 Django Admin 或最小管理视图配置 CRM 试点应用、角色、权限、角色映射和审批规则。

**验收标准：**
- [ ] 管理员可以配置 CRM app、roles、permissions、mappings、approval rules 和 cache TTL。
- [ ] 没有 approval rule 的 role 不可申请。
- [ ] 管理员可以签发和轮换静态 app token。
- [ ] 管理员可以为 CRM 创建 OAuth client credentials。

**验证：**
- [ ] Admin smoke test 从空状态创建 CRM 配置。
- [ ] 测试验证不可申请角色会被排除。

**依赖：** 任务 2-3

**预估范围：** M

### 任务 6：构建员工申请流程

**说明：** 让员工以 permanent 或 timed 授权有效期申请 CRM roles。

**验收标准：**
- [ ] 员工可以查看可申请的 CRM roles。
- [ ] 员工必须选择 permanent 或 timed 有效期。
- [ ] timed 申请必须填写授权记录过期日期。
- [ ] 提交会创建 AccessRequest 和审计事件。

**验证：**
- [ ] 端到端 smoke test 覆盖 Authentik 登录、role 选择、有效期选择和请求提交。
- [ ] 单元测试覆盖无效有效期选择。

**依赖：** 任务 4-5

**预估范围：** M

### 任务 7：集成 DingTalk 审批

**说明：** 创建 DingTalk 审批实例，并处理 grant、change 和 revoke 请求的 callback。

**验收标准：**
- [ ] 请求提交会使用 `EasyAuth Access Request` 模板创建 DingTalk 审批实例。
- [ ] EasyAuth 保存 DingTalk process instance ID。
- [ ] Callback 处理会校验真实性、请求状态和 process ID。
- [ ] 重复 callback 是幂等的。
- [ ] 拒绝审批不会改变授权记录。

**验证：**
- [ ] Mock DingTalk 测试覆盖创建失败、批准、拒绝、重复批准 callback、格式错误 callback 和未知 process instance。

**依赖：** 任务 6

**预估范围：** M

### 任务 8：应用授权记录并端到端查询

**说明：** 将已批准请求应用到 AccessGrant，并证明 CRM app 可以查询得到的 roles 和 permissions。

**验收标准：**
- [ ] 已批准的 grant request 会为每个 user/app 创建或更新一个 active grant。
- [ ] 已批准的 change 会更新目标 role set。
- [ ] 已批准的 revoke 会移除 active access。
- [ ] create、change、revoke 和 expiry 都会递增 version。
- [ ] 每个状态变更步骤都有 audit events。

**验证：**
- [ ] 端到端测试覆盖请求、DingTalk 审批、授权记录应用和 CRM 权限查询。
- [ ] 测试覆盖拒绝审批和授权记录应用失败。

**依赖：** 任务 3 和 7

**预估范围：** M

### 任务 9：添加紧急撤权

**说明：** 允许管理员立即撤销访问权限，但不得授予或增加访问权限。

**验收标准：**
- [ ] 管理员可以紧急撤销某用户对某应用的授权记录。
- [ ] 紧急撤权会写入审计原因、actor、target、old version 和 new version。
- [ ] 紧急撤权在审计日志和权限查询中可见。

**验证：**
- [ ] 测试证明紧急撤权不能授予权限。
- [ ] 紧急撤权后的权限查询返回无活跃访问权限。

**依赖：** 任务 8

**预估范围：** S

### 任务 10：打包 CRM 试点集成

**说明：** 提供集成包，让 CRM 可以在一个工作日内接入。

**验收标准：**
- [ ] API 文档说明静态 token 和 OAuth2 client-credentials 两种模式。
- [ ] 文档说明 Authentik UID 作为 `user_id`。
- [ ] 文档说明 cache TTL、version 语义和授权记录有效期。
- [ ] Sample CRM client 可以使用两种凭据模式查询权限。

**验证：**
- [ ] Manual QA 运行完整 CRM 试点流程，从申请到权限查询。
- [ ] Sample client 使用静态 token 和 OAuth2 access token 均成功。

**依赖：** 任务 1-9

**预估范围：** M

## 试点配置输入

这些不是架构阻塞项，但必须在试点配置期间提供：

- 实际 Authentik issuer URL、client ID、client secret 和 allowed callback URL。
- 实际 DingTalk app key/client ID、secret、agent ID 和 approval process code。
- CRM app owner 和首个 approver routing rule。
- 生产域名和 HTTPS 证书计划。

## 资料来源

- Django 下载和支持策略：https://www.djangoproject.com/download/
- Django 5.2 发布说明和 LTS 标记：
  https://docs.djangoproject.com/en/5.2/releases/5.2/
- Django REST Framework serializers：
  https://www.django-rest-framework.org/api-guide/serializers/
- Django OAuth Toolkit：
  https://django-oauth-toolkit.readthedocs.io/en/latest/
- Django OAuth Toolkit client credentials：
  https://django-oauth-toolkit.readthedocs.io/en/stable/getting_started.html#client-credential
- Authlib OAuth web clients：
  https://docs.authlib.org/en/latest/oauth2/client/web/
- Authentik OAuth Source：
  https://docs.goauthentik.io/users-sources/sources/protocols/oauth/
- Authentik source property mappings：
  https://docs.goauthentik.io/users-sources/sources/property-mappings/
- Authentik user properties：
  https://docs.goauthentik.io/users-sources/user/user_ref/
- Authentik notification transports：
  https://docs.goauthentik.io/sys-mgmt/events/transports/
- DingTalk user delegated access token：
  https://opensource.dingtalk.com/developerpedia/docs/learn/permission/token/user_app_token/
- DingTalk browser OAuth flow：
  https://opensource.dingtalk.com/developerpedia/docs/develop/permission/token/browser/get_user_app_token_browser/
- DingTalk app-only token：
  https://opensource.dingtalk.com/developerpedia/docs/learn/permission/token/app_only_token/
- DingTalk contact user profile：
  https://open.dingtalk.com/document/development/user-information-update
- DingTalk user details：
  https://open.dingtalk.com/document/development/queries-user-details
- DingTalk create approval instance：
  https://open.dingtalk.com/document/development/create-an-approval-instance
