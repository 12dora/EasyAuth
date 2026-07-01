# EasyAuth 业务授权运营增强架构设计

## 状态

设计草案，等待评审。

## 日期

2026-06-06

## 来源

本文承接 `docs/requirements/easyauth-business-authorization-operations.md`，并以 `docs/architecture/easyauth-architecture-design.md` 中的核心授权架构为约束。本文只设计业务授权运营增强，不重新定义 Authentik 登录、DingTalk 审批流程或公共权限查询 API。

## 设计目标

- 应用负责人可以在管理控制台中完成本 App 的业务角色、权限、审批规则、凭据和联调配置。
- 应用开发者可以获得当前 App 的接入说明、示例请求、错误语义和联调结果。
- 普通员工可以看到自己的当前授权、申请状态和即将过期授权。
- 系统管理员可以定位失败申请、失败授权、凭据风险、依赖健康和审计事件。
- 下游应用继续通过权限查询 API 消费授权快照；EasyAuth 内部用 App manifest 维护 scope、权限分组、原子权限、授权组、授权组 grant 和审批规则。

## 非目标

- 不创建或管理 Authentik Source、Application、Provider、Flow、Stage、Policy 或 Binding。
- 不实现下游应用 OIDC、SAML、Proxy 或 SCIM 登录接入。
- 不实现 DingTalk 审批流程设计器。
- 不把 DingTalk 审批结果直接作为授权事实。
- 不让 App manifest 直接授予用户权限；manifest 只定义目录事实，授权事实仍由申请、审批和 `GrantService` 产生。
- 不实现 ABAC、行级权限、字段级权限、AI 权限推荐或跨应用权限复制。

## 架构分层

```text
浏览器页面
  管理控制台、员工门户、接入说明、联调页、运营看板

边界层
  Django views、DRF serializers、Django forms、CSRF、session 权限校验

运营服务层
  AppConfigurationService
  AppManifestImportService
  CredentialOperationService
  PermissionQueryTestService
  GrantFailureRecoveryService
  DependencyHealthService

领域服务层
  AccessRequestService
  GrantService
  AppCredentialService
  OAuthClientService
  AuditService
  PermissionQueryService

持久化层
  App、AppScope、Permission、PermissionGroup、AuthorizationGroup、AuthorizationGroupGrant、PermissionTemplateVersion
  ApprovalRule、AccessRequest、AccessGrant、AppCredential、AuditLog
```

边界层负责解析不可信输入；运营服务层负责编排和校验；领域服务层负责状态变更；持久化层保存事实和可追溯记录。

## 用户与权限边界

### 普通员工

- 只能读取自己的 `AccessGrant`、`AccessRequest` 和授权到期提醒。
- 可以提交新增权限申请。
- 二期再支持变更、撤销和续期申请。
- 不能直接创建、编辑或禁用 App、AuthorizationGroup、Permission、ApprovalRule 或凭据。

### 应用负责人

- 通过 `AppMembership(role=owner)` 获得某个 App 的运营权限。
- 只能管理自己负责 App 的 scope、Permission、AuthorizationGroup、AuthorizationGroupGrant、ApprovalRule、PermissionGroup、manifest 版本和凭据。
- 可以查看本 App 的申请、授权、审计和联调结果。
- 不能执行全局审计、全局紧急撤权或跨 App 配置。

### 应用开发者

- 通过 `AppMembership(role=developer)` 查看接入资料和联调页。
- 可以读取 app_key、端点、错误码、示例和权限目录。
- 不能创建或轮换凭据，除非同时具备 owner 权限。

### 系统管理员

- 可以管理 AppMembership。
- 可以查看全局审计、依赖健康和失败恢复队列。
- 可以执行紧急撤权和受控 `grant_failed` 重试。

## 数据模型设计

### AppMembership

用途：记录应用负责人和开发者归属，限制管理控制台访问范围。

关键字段：

- `id`
- `app_id`
- `user_id`
- `role`: `owner`、`developer`
- `is_active`
- `created_at`
- `updated_at`

约束：

- `app_id + user_id + role` 唯一。
- 非 active membership 不授予管理权限。
- 系统管理员不依赖 AppMembership，可管理所有 App。

### PermissionGroup

用途：表达 App manifest 中的权限目录分组和手工维护的模块分组。

关键字段：

- `id`
- `app_id`
- `key`
- `name`
- `description`
- `parent_id`
- `display_order`
- `depth`
- `is_active`
- `created_at`
- `updated_at`

约束：

- `app_id + key` 唯一。
- 最大深度默认为 5。
- parent 必须属于同一个 App。
- 不能形成环。
- group 不是 permission，不能被授予用户，也不能出现在公共权限查询 API 中。

### Permission 扩展

建议补齐字段：

- `group_id`
- `deprecated_at`
- `deprecated_reason`

规则：

- `group_id` 可以为空，表示暂未归类。
- group 必须与 Permission 属于同一个 App。
- 同一 Permission 同一时间只能有一个直接父 group。
- `deprecated_at` 不等于删除；历史授权、审计和 RolePermission 仍可引用该 Permission。

### Manifest 版本记录

用途：记录下游应用提供的 App manifest 快照，以及导入行为的可追溯信息。短期复用 `PermissionTemplateVersion` 表时，语义必须按 manifest 版本理解，不能再把它当作只包含 group/permission 树的模板。

关键字段：

- `id`
- `app_id`
- `version`
- `source`: `upload`、`paste`、`manual`
- `content_hash`
- `raw_template`
- `import_summary`
- `imported_by`
- `imported_at`
- `status`: `imported`、`rejected`

规则：

- 同一个 App 下 `version` 单调递增。
- `content_hash` 用于识别重复 manifest。
- `raw_template` 保存原始 JSON/YAML 时必须控制大小，不能保存密钥或外部系统凭据。
- `import_summary` 记录新增、禁用、移动、重命名和废弃结果。
- 模板预览结果不写入 `PermissionTemplateVersion`，只允许进入短期缓存或专用 Preview 记录。

### 凭据最近使用时间

静态 app token 和 OAuth2 client binding 建议补齐 `last_used_at`。认证成功后可以异步或节流更新该字段，用于凭据运营和泄露排查。该字段不能参与授权决策，也不能作为凭据有效性的唯一判断。

### 依赖健康快照

`DependencyHealthSnapshot` 记录只读健康摘要：

- Authentik OIDC 配置检查结果。
- 最近一次 Authentik 用户同步时间、结果和处理数量。
- 最近一次非 active 用户撤权结果。
- 最近一次 DingTalk 回调成功时间、失败次数和最近错误摘要。
- 最近一次授权过期清理运行时间和处理数量。

健康快照不保存 Authentik、DingTalk 或 OAuth client secret。

## App Manifest 导入流程

```text
1. 应用负责人上传或粘贴 JSON/YAML manifest。
2. 边界层解析格式并限制大小。
3. AppManifestImportService 校验 schema、key 唯一性、引用完整性和 scope 支持关系。
4. 服务按 App 当前 scope、PermissionGroup、Permission、AuthorizationGroup、AuthorizationGroupGrant 和 ApprovalRule 计算差异。
5. 页面展示新增、移动、重命名、禁用和废弃清单。
6. 应用负责人确认导入。
7. 服务在事务中写入 App 基本信息、scope、权限分组、权限、授权组、授权组 grant、审批规则和 manifest 版本记录。
8. 通过统一目录版本服务提升 `App.catalog_version`。
9. 写入 manifest 导入审计事件。
```

导入规则：

- 新出现的 scope、permission group、permission 和 authorization group 可以创建为 active。
- manifest 缺失但已有引用的 Permission 只能标记 inactive 或 deprecated。
- manifest 缺失且无任何引用的 Permission 也建议先 inactive，不做物理删除。
- group key 改名视为新增 group 加旧 group inactive，除非用户明确选择“重命名展示名”。
- permission key 的业务含义变化必须新建 key。

## 配置完整性检查

配置完整性不改变授权事实，只输出发布前风险。

最低检查项：

- active App 至少有一个 active Permission。
- active App 至少有一个 active AuthorizationGroup。
- active App 至少有一个 active owner。
- active App 至少有一个 active 静态 app token 或 active OAuth2 client binding。
- requestable AuthorizationGroup 必须存在 active ApprovalRule。
- AuthorizationGroupGrant 不能指向 inactive AuthorizationGroup 或 Permission。
- active Permission 必须声明 supported_scopes。
- active Permission 不应归属 inactive PermissionGroup。

结果分级：

- `blocking`：阻止进入“可申请”状态。
- `warning`：允许保存，但需要在控制台提示。
- `info`：仅用于运营提示。

## RolePermission 矩阵

矩阵按 PermissionGroup 展示 Permission，列为 Role，行或树节点为 Permission。

保存规则：

- 前端提交矩阵差异，不提交完整授权事实。
- 服务端重新读取 Role、Permission 和 App，校验全部对象属于同一个 App。
- 保存 RolePermission 时必须写审计日志，记录旧集合、新集合和 actor。
- 矩阵配置不会直接影响既有 AccessGrant 的 roles，但会影响后续权限解析中角色展开出的 permissions。

## 凭据运营

凭据操作入口只封装现有 `AppCredentialService` 和 `OAuthClientService`。

安全规则：

- 静态 app token 明文只在创建或轮换响应中展示一次。
- OAuth2 client secret 明文只在创建响应中展示一次。
- 明文 token 和 secret 不进入列表页、详情页、审计 metadata、普通日志或浏览器持久存储。
- 禁用凭据后，联调测试和下游 API 都应安全失败。
- 轮换建议默认创建新凭据，不立即删除旧凭据，由应用负责人确认旧凭据下线后禁用。

## 联调测试台

联调测试台用于验证真实权限查询响应。

输入：

- App。
- 测试用户 Authentik `sub`。
- 凭据选择器：现有 active 凭据、OAuth2 client binding，或一次性粘贴 token。

执行规则：

- 服务端执行一次真实权限解析或真实认证链路。
- 如粘贴 token，只在本次请求内使用，不落库，不写审计 metadata。
- 返回 HTTP 状态码、错误码、roles、permissions、version、expires_at 和中文解释。
- 写入 `permission_query_test_executed` 审计事件，但只记录 credential 类型和 ID，不记录明文。

## 员工门户增强

一期新增视图：

- “我的权限”：展示 active grant 的 App、roles、permissions、version、授权类型和过期时间。
- “我的申请”：展示状态、申请角色、期限、原因、提交时间和授权落库状态。
- “即将过期”：展示未来 14 天内到期的授权。

规则：

- 员工只能读取自己的记录。
- 申请选项仍只展示 active、requestable 且有 active ApprovalRule 的 Role。
- 页面必须明确 `approved` 不等于权限已生效，只有 `grant_applied` 表示授权落库。

## 运营看板与失败恢复

运营看板查询：

- AccessRequest 按 App、用户、状态和时间范围筛选。
- AccessGrant 按 App、用户、状态、过期时间和 version 筛选。
- `grant_failed` 按失败原因、可重试性和最近失败时间筛选。
- 审计日志按 actor、target、event type 和时间范围筛选。

失败恢复规则：

- `grant_failed` 重试必须先确认申请仍是 approved 且未 grant_applied。
- 重试必须复用 `GrantService`。
- 重复重试同一个已成功处理的申请必须幂等返回，不得再次递增授权版本。
- 不可重试失败只能显示处理建议，不能提供重试按钮。

紧急撤权规则：

- 只能减少权限。
- 必须记录原因。
- 必须写入审计日志。
- 应用负责人不能执行全局紧急撤权；系统管理员可以执行。

## 管理端 API 边界

管理端 API 只服务 EasyAuth 控制台，不作为下游应用契约，必须统一放在 `/console/api/v1/` 下。员工门户增强 API 必须统一放在 `/portal/api/v1/` 下。

规则：

- 使用 Django session 和 CSRF。
- 每个接口先校验当前用户是否是系统管理员或目标 App 的 active membership。
- 所有列表分页。
- 所有写操作记录审计。
- 不接受下游 app token。
- 不返回明文历史凭据。
- 员工门户 API 只能访问当前 session 用户自己的资源。

接口设计见 `docs/api/easyauth-authorization-operations-api-design.md`。

## 阶段化实施计划

### 阶段 1（OPS-1）：配置完整性与接入联调

阶段目标：

- 建立 App 负责人边界、权限模板、配置完整性、凭据运营和联调测试的最小可用闭环。
- 让应用负责人可以从空 App 配置到联调成功，不再依赖直接编辑底层表。

交付物：

- `AppMembership`。
- `AppScope`、`PermissionGroup`、`AuthorizationGroup`、`AuthorizationGroupGrant`、manifest 版本记录和 Permission 分组/废弃字段。
- `AppConfigurationService`。
- `AppManifestImportService`。
- 授权组 grant 配置和兼容期 RolePermission 矩阵配置。
- 凭据创建、轮换、禁用入口。
- 联调测试台和接入说明页。

验收标准：

- 应用负责人只能管理自己负责的 App。
- manifest 支持 scope、permission group、permission、authorization group、grant 和 approval rule。
- manifest 导入不会删除历史 Permission，也不会改变既有 `Permission.key` 含义。
- 目录配置变更后必须提升 `App.catalog_version`，权限查询快照通过 grant version 与 catalog version 表达授权事实版本。
- 联调测试可以展示真实权限查询结果和常见错误解释。

约束：

- 阶段 1 不实现员工变更、撤销、续期申请。
- 阶段 1 不提供 Authentik 或 DingTalk 配置入口。
- 凭据明文只允许一次性展示，不写入审计 metadata。
- 所有配置写操作必须写审计日志。

验证方式：

- 模型测试覆盖 AppMembership、PermissionGroup、PermissionTemplateVersion 的唯一性和跨 App 约束。
- 服务测试覆盖模板预览、确认、差异计算和配置完整性分级。
- 浏览器冒烟覆盖从空 App 到联调成功。

### 阶段 2（OPS-2）：员工授权门户增强

阶段目标：

- 让员工看到自己的有效授权、申请状态和即将过期授权。
- 明确审批通过和授权生效之间的状态差异。

交付物：

- “我的权限”页面或同源私有 API。
- “我的申请”状态解释增强。
- “即将过期”授权视图。

验收标准：

- 员工只能读取自己的 AccessGrant 和 AccessRequest。
- 员工可以看到 roles、permissions、version、授权类型和过期时间。
- 页面明确 `approved` 不等于 `grant_applied`。
- 可申请 Role 筛选仍复用 active、requestable 和 active ApprovalRule 规则。

约束：

- 门户不直接写 `AccessGrant`。
- 门户不展示 Authentik Application Dashboard。
- 门户不提供应用登录配置或 SSO 管理能力。

验证方式：

- 门户集成测试覆盖当前授权、申请状态和 14 天内即将过期授权。
- 浏览器冒烟覆盖提交申请和状态展示。

### 阶段 3（OPS-3）：运营看板与失败恢复

阶段目标：

- 让系统管理员可以定位审批回调、授权落库、过期清理、离职撤权和凭据风险。
- 对可重试失败提供受控恢复入口。

交付物：

- AccessRequest 和 AccessGrant 筛选看板。
- `grant_failed` 重试入口。
- 紧急撤权入口。
- `DependencyHealthSnapshot` 与健康状态页。
- 审计筛选。

验收标准：

- 管理员可以筛选 `grant_failed`、即将过期授权和紧急撤权记录。
- 可重试失败不会对已 `grant_applied` 请求再次递增 version。
- 紧急撤权只能减少权限。
- 健康状态页不暴露外部系统 secret。

约束：

- 失败恢复必须调用 `GrantService`。
- 健康状态只读，不写外部系统配置。
- 只有系统管理员可以执行全局重试和紧急撤权。

验证方式：

- 集成测试覆盖重试幂等、紧急撤权后权限查询为空、健康快照脱敏。
- 审计测试覆盖失败重试、紧急撤权和健康检查事件。

### 阶段 4（OPS-4）：变更、撤销和续期申请

阶段目标：

- 补齐员工授权生命周期的自助变更、撤销和续期能力。
- 让生命周期变更继续保持审批、授权落库和审计边界。

交付物：

- change、revoke、renew 申请入口。
- 对应审批回调处理。
- 授权变更、撤销和续期的 `GrantService` 编排。
- 员工门户状态解释和运营看板筛选。

验收标准：

- change 只影响目标 App 下的角色和权限集合。
- revoke 只能减少权限。
- renew 不能绕过高风险 Role 的最长期限限制。
- 每次授权事实变化都递增 version 并写审计日志。

约束：

- DingTalk 仍只是流程通过证据。
- 任何生命周期变更都不能绕过 `GrantService`。
- 公共权限查询 API 不增加强制字段。

验证方式：

- 服务测试覆盖 change、revoke、renew 的状态机和非法状态。
- DingTalk mock 回调测试覆盖重复回调和授权失败。
- 端到端冒烟覆盖续期前后 `version` 与 `expires_at` 变化。

## 验证策略

- 模型测试覆盖唯一性、跨 App 约束、最大深度和环检测。
- 服务测试覆盖模板导入、差异计算、不可删除历史 Permission、配置完整性分级。
- API 测试覆盖管理端鉴权、分页、错误格式和敏感字段保护。
- 集成测试覆盖联调测试与公共权限查询 API 响应一致。
- 浏览器冒烟覆盖应用负责人从空 App 到联调成功的路径。

## 开放问题

- 应用负责人是否只来自 EasyAuth 本地 AppMembership，还是后续从 Authentik group 同步。
- 高风险 Role 是否需要最长授权期限和额外审批人。
- DingTalk 审批人是否保持固定 userid，还是支持直属主管等动态路由。
- 权限模板是否需要签名或来源白名单。
- 接入示例是否继续作为页面代码片段，还是发布 Python 和 TypeScript SDK。
