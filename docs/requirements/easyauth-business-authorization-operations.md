# EasyAuth 业务授权运营增强需求方案

## 状态

提议中，待评审。

## 日期

2026-06-06

## 背景

EasyAuth 当前定位是单公司内部部署的集中式授权层。根据现有架构设计，Authentik 是登录身份、OIDC subject 和用户在职状态的权威来源；DingTalk 只承担审批流程；EasyAuth 是已连接内部应用的业务授权事实来源。

本需求不是新增一个 IAM、SSO 或应用接入平台，而是在现有 EasyAuth 授权闭环之上补齐产品化运营能力，让应用负责人、员工和应用开发者不需要直接操作零散 Django Admin 表或阅读底层模型就能完成业务权限配置、申请、联调和排障。

一句话边界：

```text
Authentik 负责“你是谁、能不能登录应用”。
EasyAuth 负责“审批后你在应用里能做什么”。
```

## 已核对的现有架构与功能

新增需求必须复用下列既有设计和实现，不重复定义新的事实来源。

| 来源 | 已有内容 | 本需求处理方式 |
| --- | --- | --- |
| `docs/architecture/easyauth-architecture-design.md` | 已明确 EasyAuth 不替代 Authentik 的认证和身份生命周期能力，也不替代 DingTalk 的审批流程能力 | 新需求不包含上游认证源向导、OIDC/SAML Provider、SCIM Provider 或 DingTalk 审批流设计器 |
| `docs/architecture/easyauth-architecture-design.md` | 已定义 `App`、`Role`、`Permission`、`ApprovalRule`、`AccessRequest`、`AccessGrant` 和权限查询 API 契约 | 新需求在此基础上引入 scope、授权组和 scoped grant 运营能力，不重建上游认证模型 |
| `src/easyauth/applications/models.py` | 已实现应用、角色、权限、角色权限映射、审批规则和静态凭据模型 | 复用现有模型，新增界面必须通过服务层或模型约束保存 |
| `src/easyauth/applications/admin.py` | 已有 Django Admin 基础配置，且 `AppCredential` 禁止直接新增、修改和查看 token hash | 新需求将 Django Admin 能力产品化为受控管理控制台，不降低凭据保护 |
| `src/easyauth/applications/services.py` | 已实现静态 app token 创建、轮换、禁用、hash 存储和 `AppPrincipal` | 新需求只增加安全操作入口和一次性展示体验，不改变 token 语义 |
| `src/easyauth/applications/oauth.py`、`src/easyauth/applications/oauth_models.py` | 已实现 OAuth2 client credentials 与 App 绑定 | 新需求只把创建、禁用、联调状态可视化，不新增下游 OIDC 登录能力 |
| `src/easyauth/api/views.py`、`src/easyauth/api/authentication.py` | 已实现 `GET /api/v1/apps/{app_key}/users/{user_id}/permissions` 和 Bearer app 凭据认证 | 新需求继续复用该查询入口，并通过 `catalog_version` 表达目录配置版本 |
| `src/easyauth/grants/services.py`、`src/easyauth/grants/query.py` | 已实现授权创建、变更、撤销、过期、权限解析和版本语义 | 新需求只增加人工运营入口、状态可视化和失败恢复流程 |
| `src/easyauth/accounts/services.py` | 已实现 Authentik 用户同步后对非 active 用户撤权 | 新需求只展示同步健康和撤权结果，不配置 Authentik Source |
| `src/easyauth/portal/forms.py`、`src/easyauth/portal/views.py`、`src/easyauth/portal/templates/portal/home.html` | 已有员工访问申请表单和申请状态列表 | 新需求扩展为“我的权限、申请、变更、撤销、即将过期”，不替代 Authentik Application Dashboard |
| 现有 `Permission.key` | 当前是扁平业务权限 key，适合下游应用消费 | 新需求新增 App manifest、scope、权限分组和授权组作为配置层；权限查询响应按授权快照返回有效 permission |

## 明确不做

以下能力与 Authentik 或既有 EasyAuth 核心闭环重叠，不能纳入本需求一期范围：

- 不提供上游认证源接入向导。
- 不创建或管理 Authentik Source。
- 不创建或管理 Authentik Application、Provider、Flow、Stage、Policy、Binding。
- 不实现下游应用 OIDC/SAML/Proxy 登录。
- 不实现 SCIM Provider 或 SCIM Source。
- 不替代 Authentik Application Dashboard。
- 不让员工在 EasyAuth 中配置登录权限、MFA、密码策略或应用 SSO。
- 不重新设计现有权限查询 API。
- 不让 DingTalk 审批结果直接成为授权事实。
- 不实现 ABAC、行级权限、字段级权限、AI 权限推荐或跨应用权限复制。
- 不让 App manifest 直接授予用户权限；manifest 只能定义应用可用授权目录，授权仍由申请、审批和 `GrantService` 产生。

## 需求目标

本需求目标是把现有授权闭环从“工程可用”提升到“运营可用”：

- 应用负责人可以在受控界面中配置本应用业务角色、权限、审批规则和接入凭据。
- 下游应用可以提供 App manifest，EasyAuth 根据 manifest 维护本应用的 scope、模块分组、权限目录、授权组和审批规则。
- 员工可以查看自己已有业务权限、提交新增权限申请、查看申请状态，并识别即将过期的授权。
- 应用开发者可以从应用详情页获得自动生成的接入说明、示例请求和联调结果。
- 系统管理员可以看到授权配置完整性、失败授权、过期撤权、离职撤权和审计记录。
- 下游应用继续通过现有权限查询 API 获取授权事实，无需改接新的 SSO 协议。

## 用户角色

### 普通员工

普通员工只能管理自己的访问申请和授权可见性。

- 查看当前业务权限。
- 查看即将过期授权。
- 新增权限申请。
- 申请变更已有角色。
- 申请撤销不再需要的权限。
- 查看申请状态和审批结果。

普通员工不能直接创建应用、角色、权限、审批规则或应用凭据。

### 应用负责人

应用负责人只管理自己负责的业务应用。

- 查看应用配置完整性。
- 配置授权组、业务权限、scope 和授权组 grant。
- 配置可申请授权组和对应审批人。
- 创建或轮换 EasyAuth app token。
- 创建或查看 OAuth2 client credentials 绑定状态。
- 使用联调工具验证测试用户的权限响应。
- 查看本应用授权记录、申请记录和审计事件。

应用负责人不能配置 Authentik Provider、Source、Flow、MFA 或公司级用户组。

### 系统管理员

系统管理员负责全局安全和兜底运营。

- 管理应用负责人归属。
- 处理 `grant_failed`、审批回调异常和凭据泄露。
- 执行紧急撤权。
- 查看全局审计日志。
- 查看 Authentik 同步和 DingTalk 回调健康状态。

### 应用开发者

应用开发者只消费接入资料。

- 查看 app_key、API 端点、认证方式、错误码和缓存规则。
- 获取 curl、Python、TypeScript 示例。
- 使用联调页验证本应用后端接入。
- 确认应使用 Authentik OIDC subject 作为 `user_id`。

## 核心用户旅程

### 应用负责人配置业务授权

1. 应用负责人进入 EasyAuth 管理控制台。
2. 选择自己负责的业务应用。
3. 在“配置完整性”中看到缺失项，例如缺少可申请角色、缺少审批规则或缺少应用凭据。
4. 导入或维护下游应用提供的权限模板，例如 `PIPELINE_GROUP` 下的 `ALLOW_PIPELINE_CREATE`。
5. 配置 Role、Permission、RolePermission 和 ApprovalRule。
6. 生成或轮换 EasyAuth app token，明文只展示一次。
7. 在联调页输入测试用户的 Authentik `sub`。
8. EasyAuth 调用现有权限查询服务并展示 roles、permissions、version、expires_at。
9. 配置完整性通过后，应用进入“可申请”状态。

### 员工申请业务权限

1. 员工通过 Authentik 登录 EasyAuth 员工门户。
2. 员工查看“我的权限”和“可申请权限”。
3. 员工选择应用、角色、授权期限并填写原因。
4. EasyAuth 使用现有 `AccessRequestService` 创建申请。
5. DingTalk 审批通过后，EasyAuth 通过 `GrantService` 应用授权。
6. 员工在“我的权限”中看到授权已生效。
7. 下游应用继续调用现有权限查询 API 获得业务权限。

### 应用开发者接入下游应用

1. 下游应用使用 Authentik 完成用户登录。
2. 下游应用从 Authentik token 或 session 中读取 OIDC subject。
3. 下游应用后端使用 EasyAuth app token 或 OAuth2 access token 调用现有权限查询 API。
4. 下游应用按照返回的 permissions 控制页面、按钮、接口和业务操作。
5. 下游应用只缓存到 `expires_at`，并使用 `version` 识别授权变化。

## 功能范围

### 1. 业务应用授权配置台

这是现有 Django Admin 配置能力的产品化外壳，不是新的 SSO 应用管理系统。

一期能力：

- 按应用展示基本信息、状态、负责人、配置完整性和最近变更时间。
- 以目录方式展示 AuthorizationGroup 到 scoped Permission 的 grant。
- 支持创建、编辑、禁用 AuthorizationGroup 和 Permission。
- 支持维护 `AuthorizationGroup.requestable`。
- 支持维护 ApprovalRule，并在保存时提示缺少审批人的可申请授权组。
- 支持配置校验：
  - active App 至少有一个 active Permission。
  - active App 至少有一个 active AuthorizationGroup。
  - active App 至少有一个 active owner。
  - requestable AuthorizationGroup 必须有 active ApprovalRule。
  - AuthorizationGroupGrant 不能指向 inactive 目标。
  - Permission 必须声明 supported_scopes。
  - Permission 不应归属 inactive PermissionGroup。
  - ApprovalRule 目标必须属于同一个 App。
- 保存配置时必须写入审计日志。

不做：

- 不维护 Authentik Application。
- 不维护 Authentik Provider。
- 不维护应用 Launch URL 作为主入口。
- 不维护下游 SAML metadata、OIDC redirect URI 或 SCIM base URL。

### 2. App Manifest 与模块分组

下游应用应该能向 EasyAuth 提供本应用的 App manifest。manifest 是应用能力目录，不是授权记录；它用于初始化和组织 `AppScope`、`PermissionGroup`、`Permission`、`AuthorizationGroup`、`AuthorizationGroupGrant` 和 `ApprovalRule`，并帮助应用负责人按模块配置授权组到 scoped Permission 的映射。

manifest 需要支持 scope、模块分组和授权组。例如：

```json
{
  "schema_version": 1,
  "app": {"app_key": "crm", "name": "CRM"},
  "scopes": [{"key": "SELF", "name": "本人"}],
  "permission_groups": [{"key": "crm.customer", "name": "客户管理"}],
  "permissions": [
    {
      "key": "customer.profile.view",
      "name": "查看客户资料",
      "group_key": "crm.customer",
      "supported_scopes": ["SELF"]
    }
  ],
  "authorization_groups": [
    {
      "key": "sales",
      "kind": "role",
      "name": "销售",
      "grants": [{"permission": "customer.profile.view", "scope": "SELF"}]
    }
  ],
  "approval_rules": [
    {"target_type": "authorization_group", "target_key": "sales", "approver_userids": ["manager001"]}
  ]
}
```

一期能力：

- 支持应用负责人上传或粘贴 JSON/YAML manifest。
- 支持在界面中手工维护权限分组树。
- 支持 group 节点和 permission 叶子节点。
- 支持任意 permission 归属到一个直接父 group。
- 支持 group 嵌套，默认最大深度为 5 层。
- 支持同一 App 下 scope key、group key、permission key 和 authorization group key 各自唯一。
- 支持 manifest 预览、差异对比和确认导入。
- 支持新增权限、禁用缺失权限、移动分组、维护 supported scopes 和重命名展示名。
- 支持按模块分组展示授权组 grant。
- 支持在员工申请页按模块展示授权组包含的权限摘要。

关键规则：

- `Permission.key` 是下游应用消费的稳定能力标识，例如 `ALLOW_PIPELINE_CREATE`。
- group key 只用于 EasyAuth 管理和展示，不出现在权限查询 API 的 `permissions` 中。
- manifest 导入不能删除已被授权组、AccessGrant 或历史审计引用的 Permission，只能标记为 inactive 或 deprecated。
- manifest 导入不能改变既有 `Permission.key` 的含义；如业务含义变化，应新增 key 并废弃旧 key。
- 权限树不能有环。
- 同一个 Permission 同一时间只能有一个直接父 group，避免在申请页和审计页出现歧义。
- manifest 不授予任何人权限；只有 AccessRequest、审批结果、AuthorizationGroup grant、direct grant 和 `GrantService` 才会影响授权事实。

不做：

- 不把 group 当作可返回给下游应用的权限。
- 不让员工直接申请单个 permission；MVP 以 AuthorizationGroup 作为主要申请单元。
- 不支持跨 App 复用 manifest。
- 不根据权限模板自动创建 Authentik group、role 或 entitlement。
- 不支持模板中的条件表达式、ABAC 规则或运行时代码。

### 3. 应用凭据运营

这是现有 `AppCredentialService` 和 `OAuthClientService` 的安全操作入口。

一期能力：

- 创建静态 app token，明文只展示一次。
- 轮换静态 app token。
- 禁用静态 app token。
- 创建 OAuth2 client credentials 绑定。
- 展示凭据类型、状态、创建时间、禁用时间和最近使用时间。
- 禁止在列表、详情、日志、审计 metadata 中展示明文 token 或 secret。
- 所有创建、轮换、禁用动作写入审计日志。

不做：

- 不创建用户登录用 OIDC client。
- 不向前端应用下发 client secret。
- 不提供绕过 EasyAuth 权限查询 API 的授权 token。

### 4. 联调测试台

联调测试台用于验证现有权限查询 API 的真实响应。

一期能力：

- 输入或选择测试用户的 Authentik `sub`。
- 选择凭据类型：静态 app token 或 OAuth2 access token。
- 服务端执行一次真实权限查询。
- 展示 HTTP 状态码、roles、permissions、version、expires_at 和错误码。
- 对常见错误给出中文解释：
  - 缺失或无效凭据。
  - 凭据绑定 App 与路径 app_key 不一致。
  - App 已禁用。
  - 用户不存在、disabled 或 departed。
  - 用户没有有效授权。
- 提供可复制 curl 示例。
- 提供 Python 和 TypeScript 最小示例。

不做：

- 不模拟 Authentik 登录。
- 不生成 OIDC/SAML 登录代码。
- 不在浏览器中保存应用凭据明文。

### 5. 员工授权门户增强

这是现有访问申请门户的扩展，不是应用启动门户。

一期能力：

- “我的权限”：展示当前 active grant 的应用、角色、权限、授权类型、过期时间和 version。
- “申请权限”：沿用现有可申请角色筛选逻辑，只展示 active、requestable 且有 active ApprovalRule 的角色。
- “我的申请”：展示申请状态、申请角色、期限、原因、提交时间、审批结果和授权落库状态。
- “即将过期”：展示未来 14 天内到期的授权。
- 申请提交后明确提示：审批通过不等于授权完成，只有状态变为 `grant_applied` 才表示权限生效。

二期能力：

- 员工发起变更申请。
- 员工发起撤销申请。
- 到期前续期申请。

不做：

- 不展示或管理 Authentik Application Dashboard。
- 不判断员工能否登录某个应用。
- 不维护应用入口聚合页，最多展示应用负责人配置的说明链接或跳转提示。

### 6. 审批与授权运营看板

一期能力：

- 按应用、员工、状态和时间范围查询 AccessRequest。
- 标记并筛选 `grant_failed`。
- 对可重试的 `grant_failed` 提供受控重试入口。
- 展示 DingTalk process instance ID、最近回调时间和回调处理结果。
- 展示授权版本变化。
- 支持系统管理员执行紧急撤权。

不做：

- 不在 EasyAuth 内实现 DingTalk 审批流程设计器。
- 不把 DingTalk 审批状态当作最终授权状态。
- 不允许应用负责人绕过审批直接授予权限。

### 7. 依赖健康状态页

该页面只做只读健康检查，不做外部系统配置。

一期能力：

- 展示 Authentik OIDC 配置是否可用。
- 展示最近一次 Authentik 用户同步结果。
- 展示最近一次非 active 用户撤权结果。
- 展示 DingTalk 回调最近成功时间、失败次数和最近错误。
- 展示 Celery 授权过期清理最近运行时间和处理数量。

不做：

- 不配置 Authentik Source。
- 不配置 Authentik Flow。
- 不配置 DingTalk 审批模板。

### 8. 接入文档自动生成

应用详情页根据当前 App 配置生成只读接入说明。

一期内容：

- app_key。
- 权限查询 API 地址。
- Bearer token 使用方式。
- OAuth2 client credentials 使用方式。
- Authentik `sub` 作为 `user_id` 的说明。
- roles、permissions、version、expires_at 字段语义。
- 401、403、422、500 错误说明。
- 缓存和撤权 SLA。
- curl、Python、TypeScript 示例。
- 本应用当前 Role 和 Permission 清单。
- 本应用当前 manifest 版本、模块分组树和权限 key 清单。

不做：

- 不生成 Authentik Provider 配置。
- 不生成 SAML metadata。
- 不生成 SCIM schema。
- 不把 SDK 作为一期依赖。

## 公共 API 影响

一期不修改现有下游应用权限查询 API：

```http
GET /api/v1/apps/{app_key}/users/{user_id}/permissions
Authorization: Bearer {app_token_or_oauth_access_token}
```

响应必须表达授权事实和版本：

- `user_id`
- `app_key`
- `roles` 或等价的授权组摘要
- `permissions`
- `version`、`grant_version` 或 `catalog_version`
- `expires_at`

manifest 中的 group key 不作为 permission 返回。下游应用收到的 `permissions` 只包含 `customer.profile.view` 这类原子权限 key，目录配置变化通过 `catalog_version` 参与快照版本。

如后续新增管理端 API，必须满足：

- 仅供 EasyAuth 管理控制台使用。
- 需要 Django session 或明确管理端鉴权。
- 不作为下游应用接入契约。
- 不允许绕过 `GrantService` 写入授权记录。

## 数据模型影响

一期优先复用现有数据模型。确需新增字段时，必须先评审是否可以从现有模型或 Authentik 获得。

建议新增或补齐的最小数据：

- 应用负责人与应用的关系，用于限制应用负责人只能管理自己负责的 App。
- manifest 版本，用于记录下游应用提供的授权目录快照。
- 权限模块分组树，用于表达 group 节点、父子关系、展示顺序和层级路径。
- Permission 与模块分组的归属关系，用于按模块展示和导入差异计算。
- 凭据最近使用时间，用于凭据运营和泄露排查。
- DingTalk 回调处理摘要，用于运营看板展示。
- 依赖健康检查快照，用于只读状态页。

不得新增的数据：

- Authentik 用户密码、MFA 状态或登录策略副本。
- Authentik Source、Provider、Flow、Policy 的配置副本。
- DingTalk 审批流程定义副本。
- 下游应用 SAML/OIDC/SCIM 协议配置副本。
- 由权限模板直接生成的用户授权事实副本。

## 权限与安全要求

- 普通员工只能查看和申请自己的授权。
- 应用负责人只能管理自己负责 App 的业务授权配置。
- 系统管理员才能执行全局审计查询、紧急撤权和失败重试。
- 所有配置变更、凭据操作、授权重试和紧急撤权必须写审计日志。
- app token 和 client secret 明文只允许在创建时一次性展示。
- 管理端和员工端必须复用现有服务层，不能直接写 `AccessGrant`。
- 联调测试不能在页面、日志或审计 metadata 中保存明文凭据。

## 验收标准

### 产品验收

- 应用负责人可以在不直接进入 Django Admin 原始表的情况下完成一个试点 App 的业务角色、权限、审批规则和凭据配置。
- 配置完整性检查能阻止 requestable AuthorizationGroup 缺少 active ApprovalRule 的发布状态。
- 权限模板支持 `PIPELINE_GROUP -> ALLOW_PIPELINE_CREATE` 这类模块分组，并支持至少 5 层 group 嵌套。
- 导入权限模板后，RolePermission 矩阵可以按模块展示 Permission。
- 应用负责人可以使用联调测试台验证测试用户的真实权限查询响应。
- 自动生成的接入说明足以让下游应用开发者完成权限查询 API 接入。
- 员工可以查看当前授权、提交新权限申请并查看申请状态。
- 系统管理员可以筛选失败申请、失败授权、即将过期授权和紧急撤权记录。
- 页面中没有任何上游认证源、OIDC/SAML Provider、SCIM Provider 或 Authentik Flow 配置入口。

### 技术验收

- 现有权限查询 API 响应字段和语义保持向后兼容。
- manifest 导入不会让 group key 出现在权限查询 API 的 `permissions` 中。
- 模板删除或改名不会破坏历史授权、历史审计和既有 `Permission.key`。
- 所有授权写入仍通过 `GrantService`。
- 所有访问申请写入仍通过 `AccessRequestService`。
- 所有应用凭据操作仍通过现有凭据服务。
- 审计日志覆盖配置变更、凭据操作、联调查询、失败重试和紧急撤权。
- 非 active Authentik 用户仍不能获得有效 permissions。
- 禁用 App 或禁用凭据后，联调测试和下游 API 都表现为安全失败。

## 分期计划

以下阶段使用 `OPS-*` 前缀，专指业务授权运营增强，不等同于 MVP 实施计划中的 `MVP-*` 阶段。

### 阶段 1（OPS-1）：配置完整性与接入联调

阶段目标：

- 让应用负责人可以自助完成现有业务授权模型的配置、凭据准备和联调验证。
- 让应用开发者可以从应用详情页获得足够接入资料，不再依赖人工解释底层模型。
- 引入 App manifest、模块分组、scope、授权组和 scoped grant 配置。

阶段交付物：

- 构建应用详情页和配置完整性检查。
- 构建 manifest 导入、预览、差异确认和模块分组树。
- 构建 AuthorizationGroup、Permission、scope 和 grant 的配置界面。
- 构建 requestable AuthorizationGroup 的 ApprovalRule 缺失提示。
- 构建静态 app token 和 OAuth2 client credentials 的受控操作入口。
- 构建联调测试台。
- 构建接入文档自动生成页。

验收标准：

- 从空 App 到联调成功不需要直接编辑数据库。
- 包含 scope、permission group、permission、authorization group、grant 和 approval rule 的 manifest 可以成功导入并在目录中展示。
- manifest 导入只创建、移动、禁用或废弃 Permission，不删除历史 Permission。
- 目录配置保存后提升 `catalog_version`，权限查询 API 返回的 `permissions` 仍只包含原子权限 key。
- 静态 app token 和 OAuth2 client secret 明文只在创建或轮换响应中展示一次。
- 联调测试台可以展示成功响应、空权限响应和 401/403/422/500 错误解释。
- 不引入 Authentik Provider 或 Source 配置。
- 权限查询 API 必须保留授权事实查询能力，并清晰暴露 grant version 与 catalog version。

阶段约束：

- 管理端必须复用现有服务层和模型约束，不能直接写 `AccessGrant`。
- manifest 不能直接授予用户权限，不能让 group key 出现在下游 `permissions` 中。
- 凭据明文不能进入列表页、详情页、日志、审计 metadata 或浏览器持久存储。
- 应用负责人只能管理自己负责的 App；系统管理员管理 App 负责人归属。

验证方式：

- 配置完整性服务测试覆盖 blocking、warning 和 ready。
- 模板导入测试覆盖 5 层嵌套、重复 key、跨 App、历史 Permission 废弃和环检测。
- 管理控制台浏览器冒烟覆盖从空 App 到联调成功。
- `pytest`、`ruff check .`、`basedpyright` 通过。

### 阶段 2（OPS-2）：员工授权门户增强

阶段目标：

- 让员工理解自己当前拥有什么业务权限、申请到了哪一步、哪些授权即将过期。
- 保持员工门户是授权申请和可见性门户，不变成应用启动门户或 SSO 配置门户。

阶段交付物：

- 增加“我的权限”。
- 增加“即将过期”。
- 优化“我的申请”状态解释。
- 明确 `submitted`、`approved`、`grant_applied`、`grant_failed` 的业务含义。

验收标准：

- 员工可以看到自己 active grant 的 App、roles、permissions、version、授权类型和过期时间。
- 员工可以看到未来 14 天内即将过期的授权。
- 员工能区分审批通过和授权生效。
- 员工只看到自己有权查看的申请和授权。
- 员工门户不变成应用启动门户。

阶段约束：

- 门户只能读取当前登录用户自己的申请和授权。
- 提交申请仍必须调用 `AccessRequestService`，不能直接创建 grant。
- 可申请 Role 仍必须 active、requestable 且有 active ApprovalRule。
- 门户不展示 Authentik Application Dashboard，不判断用户能否登录某个应用。

验证方式：

- 门户集成测试覆盖我的权限、我的申请、即将过期和无权限访问。
- 浏览器冒烟覆盖申请提交、状态展示和过期提醒。
- 非 active 用户 session 被拒绝或重定向登录。

### 阶段 3（OPS-3）：运营看板与失败恢复

阶段目标：

- 让系统管理员可以定位和处理异常授权闭环。
- 让安全敏感操作、失败恢复和依赖健康状态可审计、可追踪、可回放分析。

阶段交付物：

- 增加申请和授权状态筛选。
- 增加 `grant_failed` 重试入口。
- 增加紧急撤权入口。
- 增加 Authentik、DingTalk、Celery 只读健康状态页。
- 增加审计筛选。

验收标准：

- 管理员可以定位审批回调失败、授权落库失败和过期清理异常。
- 管理员可以按 App、用户、状态、时间范围筛选 AccessRequest 和 AccessGrant。
- 管理员可以查看 Authentik 同步、DingTalk 回调和 Celery 清理的最近健康状态。
- 紧急撤权只能减少权限。
- 失败恢复不能重复递增已处理授权版本。
- 审计日志覆盖失败重试、紧急撤权和健康检查。

阶段约束：

- `grant_failed` 重试只能用于可重试、仍未 `grant_applied` 的申请。
- 重试必须复用 `GrantService`，不能绕过版本递增和审计。
- 紧急撤权只能由系统管理员执行，且必须填写原因。
- 健康状态页只读，不提供 Authentik 或 DingTalk 配置入口。

验证方式：

- 集成测试覆盖可重试失败、不可重试失败、重复重试和已处理申请。
- 权限查询集成测试覆盖紧急撤权后的空权限响应和 version 变化。
- 健康状态测试覆盖无 secret 输出和最近错误摘要。
- 审计测试覆盖 actor、target、event type、reason 和 metadata。

### 阶段 4（OPS-4）：变更、撤销和续期申请

阶段目标：

- 补齐员工授权生命周期的自助闭环。
- 让角色变更、主动撤销和到期续期都具备明确审批、授权变更和审计语义。

阶段交付物：

- 支持员工发起角色变更申请。
- 支持员工发起撤销申请。
- 支持员工在过期前发起续期申请。
- 补齐对应审批、授权变更和审计。

验收标准：

- 变更、撤销、续期都必须经过审批或明确的管理员授权策略。
- 变更申请只替换目标 App 下的角色集合，不影响其他 App。
- 撤销申请只能减少当前用户在目标 App 下的权限。
- 续期申请不能绕过高风险 Role 的最长期限限制。
- DingTalk 仍只是流程通过证据。
- EasyAuth 仍由 `GrantService` 写入最终授权事实。

阶段约束：

- 变更、撤销和续期不能复用新增申请的状态解释而隐藏授权落库状态。
- 已过期、已撤销或非 active 用户的申请必须被拒绝或进入人工处理。
- 所有生命周期变更必须递增 grant version 并写审计日志。
- 下游应用仍只通过现有权限查询 API 观察结果。

验证方式：

- 服务测试覆盖 grant、change、revoke、renew 的状态转换和非法状态。
- DingTalk mock 回调测试覆盖批准、拒绝、重复回调和授权失败。
- 端到端冒烟覆盖续期前后 `expires_at` 与 `version` 变化。

## 阶段推进总约束

- 每个阶段都必须保持公共权限查询 API 向后兼容。
- 每个阶段交付后必须能通过对应用户表面完成一次可观察冒烟，而不是只完成后台配置。
- 每个阶段都必须保护明文 token、client secret 和外部系统 secret。
- 每个阶段都不能让 Authentik、DingTalk 或权限模板成为授权事实来源。
- 每个阶段完成时都应更新 `docs/architecture/`、`docs/api/`、`docs/plans/` 中对应说明，避免需求、架构和实施计划分叉。

## 后续可选方向

- Python SDK 和 TypeScript SDK，只封装请求、缓存和错误处理。
- 与 Authentik Application Entitlements 做只读对照或导入建议，但不能让 Authentik Entitlements 与 EasyAuth AccessGrant 同时成为同一授权事实来源。
- 周期性权限复核。
- 批量授权和批量撤权。
- 应用负责人权限委托。

## 开放问题

- 应用负责人的身份来源是 EasyAuth 本地配置、Authentik group，还是两者结合。
- DingTalk 审批人是否只支持固定 userid，还是需要支持部门负责人、直属主管等动态路由。
- `grant_failed` 的可重试条件需要按失败原因分类。
- 是否需要给高风险 Role 设置最长授权期限。
- 接入文档中的 Python 和 TypeScript 示例是否以独立 SDK 形式发布，还是保持复制代码片段。

## 后续实现验证命令

实现本需求后，至少运行：

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py migrate --check
pytest
ruff check .
basedpyright
```

涉及浏览器页面时，还需要补充员工门户和管理控制台的端到端冒烟验证。
