# EasyAuth MVP 实施计划

## 状态

实施顺序草案。

## 日期

2026-06-05

## 来源

本计划基于 `docs/architecture/easyauth-architecture-design.md` 编写。架构文档仍然是模块边界、公共 API 语义、安全规则和 MVP 范围的事实来源。

## 概览

EasyAuth MVP 应先完成后端闭环，再开发员工前端。后端闭环包括试点内部应用授权查询、身份同步、员工访问申请服务、DingTalk 审批处理、撤权、过期清理和审计；员工门户和浏览器端到端验证只能在这些能力完成后进入。必要例外仅限 Django Admin 试点配置、Authentik 会话边界、API 契约或文档草稿等后端交付所需内容。

## 本计划采用的架构决策

- MVP 使用模块化 Django 单体，降低事务一致性、Django Admin 配置和部署复杂度。
- Authentik 是登录身份、OIDC subject 和用户在职状态的权威来源。
- EasyAuth 是已连接内部应用的授权事实来源。
- DingTalk 审批只作为流程通过证据；授权只能由 EasyAuth `GrantService` 应用。
- 开发顺序遵循后端优先：先完成模型、服务、API、外部集成、撤权和过期能力，再开发员工门户。
- 必要例外仅限 Django Admin 试点配置、Authentik 会话边界、API 契约或文档草稿、最终端到端验证。
- 静态 app token 与 OAuth2 client credentials 必须映射为相同的 `AppPrincipal` 授权语义。

## 依赖图

```text
Django 工程和质量门槛
  |
  +-- App、Role、Permission、ApprovalRule 模型
  |     |
  |     +-- App 凭据和 AppPrincipal
  |     |     |
  |     |     +-- 权限查询 API
  |     |
  |     +-- Django Admin 试点配置
  |
  +-- UserMirror 和 AuditLog
  |     |
  |     +-- Authentik 同步和离职撤权
  |
  +-- AccessRequest 和 AccessGrant 模型
        |
        +-- GrantService
              |
              +-- 权限查询 API
              +-- 员工申请后端服务
              |     |
              |     +-- DingTalk 回调授权落库
              |
              +-- 过期清理和紧急撤权
                    |
                    +-- 员工门户前端
                          |
                          +-- 试点接入包和端到端冒烟
```

本文阶段使用 `MVP-*` 前缀，专指 MVP 实施计划，不等同于业务授权运营增强需求中的 `OPS-*` 阶段。

## 阶段 1（MVP-1）：基础建设

### 阶段目标

- 建立可持续开发的 Django 工程、质量门槛和核心数据模型。
- 在不接入外部系统的前提下，先固定 App、Role、Permission、ApprovalRule、UserMirror、AuditLog、AccessRequest 和 AccessGrant 的基础约束。

### 阶段验收

- 本地项目可以运行基础检查、测试、lint 和类型检查。
- Django Admin 可以创建 CRM 试点所需的基础应用配置数据。
- 核心模型的唯一性、跨 App 约束、生命周期字段和审计只读约束都有测试覆盖。

### 阶段约束

- 阶段 1 不实现公共权限查询 API。
- 阶段 1 不接入 Authentik 或 DingTalk 真实凭据。
- 阶段 1 不开发员工门户前端。
- 阶段 1 的模型变更必须服务后续授权闭环，不能引入 IAM 或 SSO 配置模型。

### 任务 1：初始化 Django 工程和质量门槛

**说明：** 创建初始 Django 项目结构、Python 项目配置、测试框架和质量命令，让后续任务都有稳定的开发基线。

**验收标准：**

- [ ] `src/easyauth/`、`manage.py`、settings、URL routing、ASGI/WSGI entrypoints
      和测试目录已存在。
- [ ] PostgreSQL、Redis、Celery、DRF、Django OAuth Toolkit、pytest、ruff 和
      basedpyright 已在项目配置中声明。
- [ ] 本地 settings 支持开发默认值，且不提交密钥。

**验证：**

- [ ] `python manage.py check`
- [ ] `pytest`
- [ ] `ruff check .`
- [ ] `basedpyright`

**依赖：** 无

**预计触达文件：**

- `pyproject.toml`
- `manage.py`
- `src/easyauth/config/settings.py`
- `src/easyauth/config/urls.py`
- `tests/`

**预计规模：** 中

### 任务 2：实现应用配置模型

**说明：** 实现应用配置领域，包括已连接应用、角色、权限、角色权限映射和审批规则，并加入符合架构文档的数据库约束。

**验收标准：**

- [ ] `App.app_key` 稳定且唯一。
- [ ] `Role.key` 和 `Permission.key` 在同一个 app 内唯一。
- [ ] `RolePermission` 阻止跨 app 的 role/permission 映射。
- [ ] `ApprovalRule` 只能指向一个 role 或 permission，并校验目标属于同一个 app。

**验证：**

- [ ] 模型约束单元测试覆盖重复配置和跨 app 违规配置。
- [ ] `python manage.py makemigrations --check`
- [ ] `python manage.py migrate --check`
- [ ] `pytest tests/unit/applications`

**依赖：** 任务 1

**预计触达文件：**

- `src/easyauth/applications/models.py`
- `src/easyauth/applications/services.py`
- `tests/unit/applications/`

**预计规模：** 中

### 任务 3：实现用户镜像和审计日志

**说明：** 增加 Authentik 用户镜像存储和 append-only 审计日志，让领域服务可以一致识别用户并记录安全事件。

**验收标准：**

- [ ] `UserMirror.authentik_user_id` 全局唯一，并作为公共用户标识。
- [ ] `UserMirror.status` 支持 `active`、`disabled` 和 `departed`。
- [ ] `AuditLog` 记录 actor、event、target、metadata 和创建时间。
- [ ] 通过模型、Admin 保护和 `AuditService.record()` 保证审计记录 append-only。

**验证：**

- [ ] 单元测试覆盖用户唯一性、状态值和审计写入。
- [ ] Admin 冒烟确认审计记录只读。
- [ ] `pytest tests/unit/accounts tests/unit/audit`

**依赖：** 任务 1

**预计触达文件：**

- `src/easyauth/accounts/models.py`
- `src/easyauth/audit/models.py`
- `src/easyauth/audit/services.py`
- `tests/unit/accounts/`
- `tests/unit/audit/`

**预计规模：** 中

### 任务 4：实现访问申请和授权记录模型

**说明：** 增加申请和授权记录持久化，包括申请状态机字段、授权生命周期字段、授权版本号，以及规范化的角色/权限授权子表。

**验收标准：**

- [ ] `AccessRequest` 支持 `grant`、`change` 和 `revoke` 申请类型。
- [ ] timed 授权必须填写 `grant_expires_at`；permanent 授权必须为空。
- [ ] 每个 user 和 app 最多只有一条当前 `AccessGrant` 记录。
- [ ] 授权角色子表和直接权限子表只能引用同一个 app 下的对象。

**验证：**

- [ ] 单元测试覆盖状态值、生命周期约束和唯一性。
- [ ] `python manage.py makemigrations --check`
- [ ] `python manage.py migrate --check`
- [ ] `pytest tests/unit/access_requests tests/unit/grants`

**依赖：** 任务 2、任务 3

**预计触达文件：**

- `src/easyauth/access_requests/models.py`
- `src/easyauth/grants/models.py`
- `tests/unit/access_requests/`
- `tests/unit/grants/`

**预计规模：** 中

## 检查点：基础建设

- [ ] `python manage.py check`
- [ ] `python manage.py migrate --check`
- [ ] `pytest`
- [ ] `ruff check .`
- [ ] `basedpyright`
- [ ] Django Admin 可以创建 CRM 试点所需的 App、Role、Permission、RolePermission 和 ApprovalRule 配置数据。

## 阶段 2（MVP-2）：第一条可用授权查询 API

### 阶段目标

- 建立下游应用可用的第一条稳定授权查询路径。
- 让静态 app token 和 OAuth2 client credentials 都映射为相同的 `AppPrincipal`。
- 固定公共权限查询 API 的响应字段、错误语义、缓存过期和 version 规则。

### 阶段验收

- CRM 试点 App 可以使用静态 token 和 OAuth2 access token 查询同一用户权限，并得到完全一致结果。
- disabled、departed、revoked、expired 和 unknown user 场景都返回文档约定结果。
- 查询结果 roles 和 permissions 稳定排序，`expires_at` 不越过授权生命周期。

### 阶段约束

- 阶段 2 不开发员工门户。
- 阶段 2 不让 OAuth2 client credentials 变成用户登录 OIDC client。
- 阶段 2 不暴露 EasyAuth 内部数据库用户 ID。
- 阶段 2 后公共 API 只能向后兼容扩展，不能修改既有字段语义。

### 任务 5：实现 GrantService 授权语义

**说明：** 实现唯一允许创建、变更、撤销、过期或应用授权记录的服务，包括版本递增和审计写入。

**验收标准：**

- [ ] 创建、变更、撤销和过期 grant 都会递增 `version`。
- [ ] 角色展开权限和直接权限会解析为去重权限集合。
- [ ] roles 和 permissions 按 key 稳定排序后返回。
- [ ] disabled、departed、revoked 和 expired grant 不会产生 active permissions。

**验证：**

- [ ] 单元测试覆盖 active、revoked、expired、disabled 和 departed 用户。
- [ ] 单元测试断言 version 变化和审计事件。
- [ ] `pytest tests/unit/grants`

**依赖：** 任务 4

**预计触达文件：**

- `src/easyauth/grants/services.py`
- `tests/unit/grants/`

**预计规模：** 中

### 任务 6：实现静态 app token 凭据

**说明：** 增加静态 app token 创建、hash 存储、轮换、禁用，以及将 token 解析为统一 `AppPrincipal` 的 DRF 认证。

**验收标准：**

- [ ] 静态 app token 明文只在创建时展示一次。
- [ ] 数据库只存储 token hash。
- [ ] 已禁用凭据和已禁用 app 无法认证。
- [ ] 认证成功的请求会生成 `AppPrincipal(app_id, app_key, credential_type, credential_id)`。

**验证：**

- [ ] 单元测试覆盖 token hash、一次性展示、禁用和轮换。
- [ ] API 认证测试覆盖缺失、无效、禁用和有效 token。
- [ ] `pytest tests/unit/applications tests/integration/api`

**依赖：** 任务 2、任务 5

**预计触达文件：**

- `src/easyauth/applications/models.py`
- `src/easyauth/applications/services.py`
- `src/easyauth/api/authentication.py`
- `tests/unit/applications/`
- `tests/integration/api/`

**预计规模：** 中

### 任务 7：实现权限查询 API

**说明：** 实现 `GET /api/v1/apps/{app_key}/users/{user_id}/permissions`，并遵循架构文档中的响应结构、错误结构、缓存过期语义和审计行为。

**验收标准：**

- [ ] 路径中的 `app_key` 必须匹配 `AppPrincipal.app_key`；不匹配返回 403。
- [ ] 未知、disabled 或 departed 用户返回空 roles 和 permissions，且不暴露用户存在性差异。
- [ ] 没有历史授权的未知用户返回 `version: 0`；revoked 或 expired 用户返回最新 grant version。
- [ ] `expires_at` 取配置缓存 TTL 和最近 active grant 过期时间的较小值。
- [ ] 成功查询会记录 `app_permission_queried` 审计事件。

**验证：**

- [ ] 集成测试覆盖 active permissions、empty permissions、unknown user、disabled user、departed user、revoked grant、expired grant、cross-app access、disabled app 和稳定排序。
- [ ] 使用 seed 后的 CRM app 和静态 token 通过 `curl` 手动检查。
- [ ] `pytest tests/integration/api/test_permission_query.py`

**依赖：** 任务 3、任务 5、任务 6

**预计触达文件：**

- `src/easyauth/api/views.py`
- `src/easyauth/api/serializers.py`
- `src/easyauth/api/urls.py`
- `src/easyauth/grants/query.py`
- `tests/integration/api/`

**预计规模：** 中

### 任务 8：实现 OAuth2 client credentials 绑定

**说明：** 增加 Django OAuth Toolkit client credentials 支持，同时确保每个 OAuth client 精确绑定一个 EasyAuth app，并保留与静态 token 相同的 `AppPrincipal` 语义。

**验收标准：**

- [ ] OAuth client 精确绑定一个 `App`。
- [ ] `/oauth/token` 可以签发 client credentials access token。
- [ ] 同一 app 和 user 下，OAuth access token 与静态 app token 产生完全一致的权限查询结果。
- [ ] disabled app 或 invalid token 返回文档约定的 401/403 响应。

**验证：**

- [ ] 集成测试覆盖 token 签发和权限查询。
- [ ] 集成测试对比 OAuth 和静态 token 响应。
- [ ] 使用 `curl` 手动检查 `/oauth/token` 和权限查询端点。

**依赖：** 任务 7

**预计触达文件：**

- `src/easyauth/applications/oauth.py`
- `src/easyauth/api/authentication.py`
- `src/easyauth/config/urls.py`
- `tests/integration/oauth/`

**预计规模：** 中

## 检查点：API 试点

- [ ] 静态 app token 和 OAuth2 client credentials 返回相同的权限查询结果。
- [ ] CRM 试点 seed 数据可以通过 `/api/v1` 查询。
- [ ] validation、authentication、authorization、conflict、semantic validation 和 internal errors 都使用统一错误格式。
- [ ] `python manage.py check`、`pytest`、`ruff check .` 和 `basedpyright` 通过。

## 阶段 3（MVP-3）：身份、审批和后端运营能力

### 阶段目标

- 补齐身份同步、审批回调、员工申请后端、授权过期和紧急撤权，形成后端授权闭环。
- 保证所有授权写入仍通过 `GrantService`，所有申请写入仍通过 `AccessRequestService`。

### 阶段验收

- Authentik 非 active 用户会触发撤权，并让后续权限查询返回空权限。
- DingTalk mock approval 可以批准申请并通过 `GrantService` 应用 grant。
- 重复回调、过期清理和紧急撤权保持幂等。
- Django Admin 试点配置保护敏感字段和审计只读性。

### 阶段约束

- 阶段 3 不把 DingTalk 审批结果直接作为授权事实。
- 阶段 3 不配置 Authentik Source、Provider、Flow 或 MFA。
- 阶段 3 不允许管理员绕过服务层直接写 AccessGrant。
- 阶段 3 的紧急撤权只能减少权限，不能授予或增加权限。

### 任务 9：实现 Authentik 用户同步和离职撤权

**说明：** 增加 Authentik payload 解析、webhook 处理、定时同步入口、用户 upsert 行为，以及离职触发的授权撤销。

**验收标准：**

- [ ] Authentik OIDC subject 映射到 `UserMirror.authentik_user_id`。
- [ ] Webhook 和定时同步都能 upsert 用户。
- [ ] Authentik 的 `inactive`、`disabled` 或 departed 状态会映射为 EasyAuth 非 active 状态。
- [ ] 离职会撤销所有 active grants、递增 versions，并写入 `user_departure_detected` 和 `grant_revoked` 审计事件。

**验证：**

- [ ] 单元测试覆盖 Authentik payload 解析和状态映射。
- [ ] 集成测试覆盖 webhook upsert 和离职撤权。
- [ ] `pytest tests/unit/integrations/authentik tests/integration/authentik`

**依赖：** 任务 3、任务 5

**预计触达文件：**

- `src/easyauth/integrations/authentik/`
- `src/easyauth/accounts/services.py`
- `src/easyauth/tasks/authentik.py`
- `tests/unit/integrations/authentik/`
- `tests/integration/authentik/`

**预计规模：** 中

### 任务 10：强化 Django Admin 试点配置

**说明：** 配置 Django Admin 以支持试点运营，同时强制执行敏感字段处理和领域校验规则。

**验收标准：**

- [ ] App token 明文永远不会出现在列表页、详情页、日志或审计视图中。
- [ ] AuditLog 在 Admin 中只读，不能编辑或删除。
- [ ] ApprovalRule admin 会校验 role/permission 目标属于同一个 app。
- [ ] 没有审批规则的 requestable role 会作为无效试点配置展示给管理员。

**验证：**

- [ ] Admin 表单测试覆盖校验和只读行为。
- [ ] 手动 Admin 冒烟测试可以从空数据库创建 CRM App、Role、Permission、RolePermission、ApprovalRule 和 AppCredential。
- [ ] `pytest tests/integration/admin`

**依赖：** 任务 2、任务 3、任务 4、任务 6

**预计触达文件：**

- `src/easyauth/applications/admin.py`
- `src/easyauth/audit/admin.py`
- `src/easyauth/grants/admin.py`
- `tests/integration/admin/`

**预计规模：** 中

### 任务 11：实现员工访问申请后端服务

**说明：** 实现 `AccessRequestService` 的申请创建、校验和状态转换，不开发员工门户前端。后续门户只能调用该服务，不能绕过后端校验或直接创建 grant。

**验收标准：**

- [ ] 服务支持 app、requestable role、授权生命周期、过期时间和申请原因。
- [ ] 没有审批规则的 roles 或 permissions 不能创建申请。
- [ ] 提交申请会写入 `access_request_submitted` 审计事件。
- [ ] 提交后只创建 `AccessRequest`，不会直接创建 grant，且 `approved` 与 `grant_applied` 保持分离。

**验证：**

- [ ] 单元测试覆盖申请校验和状态转换。
- [ ] 集成测试覆盖服务入口创建申请、非法配置拒绝和审计写入。
- [ ] `pytest tests/unit/access_requests tests/integration/access_requests`

**依赖：** 任务 4、任务 10

**预计触达文件：**

- `src/easyauth/access_requests/services.py`
- `tests/unit/access_requests/`
- `tests/integration/access_requests/`

**预计规模：** 中

### 任务 12：实现 DingTalk 审批创建和回调

**说明：** 增加 DingTalk 审批实例创建、回调签名和 payload 处理、幂等状态转换，以及已批准申请的授权落库。

**验收标准：**

- [ ] 提交申请会创建 DingTalk 审批实例，并保存唯一 process instance ID。
- [ ] 回调处理会校验签名、process ID、payload 结构和当前申请状态。
- [ ] 重复 approved 回调不会再次递增 grant version。
- [ ] 重复 rejected 回调不会覆盖已经 applied 的 grants。
- [ ] 授权落库失败会将申请转为 `grant_failed` 并写入 `grant_apply_failed`。

**验证：**

- [ ] 单元测试覆盖 payload 解析和签名校验。
- [ ] 集成测试覆盖 approved、rejected、duplicate approved、duplicate rejected、unknown process instance、invalid signature 和 grant failure。
- [ ] 使用 DingTalk mock approval callback 进行手动冒烟测试。

**依赖：** 任务 5、任务 11

**预计触达文件：**

- `src/easyauth/integrations/dingtalk/`
- `src/easyauth/access_requests/callbacks.py`
- `src/easyauth/access_requests/services.py`
- `tests/unit/integrations/dingtalk/`
- `tests/integration/dingtalk/`

**预计规模：** 中

### 任务 13：实现授权过期清理和紧急撤权

**说明：** 增加 timed grants 的定时清理，以及只减少访问权限且保留审计性的管理员/系统紧急撤权路径。

**验收标准：**

- [ ] Celery beat 扫描 `grant_expires_at <= now()` 的 active timed grants。
- [ ] 到期 grants 会转为 `expired`、递增 version，并写入 `grant_expired`。
- [ ] 紧急撤权可以撤销 active grants，但不能授予或增加 permissions。
- [ ] 清理和紧急撤权保持幂等。

**验证：**

- [ ] 单元测试覆盖过期选择、并发/重复清理和紧急撤权。
- [ ] 集成测试覆盖过期和撤权后的权限查询。
- [ ] `pytest tests/unit/grants tests/integration/api`

**依赖：** 任务 5、任务 9

**预计触达文件：**

- `src/easyauth/grants/services.py`
- `src/easyauth/tasks/grants.py`
- `src/easyauth/admin_console/`
- `tests/unit/grants/`
- `tests/integration/api/`

**预计规模：** 中

## 检查点：后端闭环

- [ ] 后端服务可以创建 CRM role 申请，不依赖员工门户。
- [ ] DingTalk mock 可以批准该申请。
- [ ] EasyAuth 通过 `GrantService` 应用 grant。
- [ ] CRM 权限查询可以反映已应用的 grant。
- [ ] 重放回调、过期清理和紧急撤权保持幂等。
- [ ] `pytest`、`ruff check .` 和 `basedpyright` 通过；此检查点不要求浏览器冒烟。

## 阶段 4（MVP-4）：前端和试点接入包

### 阶段目标

- 在后端闭环完成后，交付员工可使用的申请表面和试点应用可使用的接入包。
- 通过浏览器和下游 API 表面证明 MVP 能按预期完成申请、审批、授权落库和权限查询。

### 阶段验收

- 员工可以通过门户提交 CRM role 申请并看到状态变化。
- 试点接入文档足以让内部应用在一个工作日内完成权限查询接入。
- 端到端冒烟覆盖 Authentik 登录、申请、DingTalk mock 审批、授权落库和 CRM 权限查询。

### 阶段约束

- 阶段 4 前端只能调用后端服务，不承载新的授权规则。
- 阶段 4 员工门户不替代 Authentik Application Dashboard。
- 阶段 4 试点接入包不发布 SDK 作为必需依赖。
- 阶段 4 不新增破坏性公共 API 字段或新的下游认证协议。

### 任务 14：实现员工门户前端

**说明：** 在后端闭环完成后，使用 Django SSR 和 HTMX 增加员工侧申请提交与状态查看界面。门户只负责调用后端服务和展示结果，不承载新的授权规则。

**验收标准：**

- [ ] 员工可以选择 app、requestable role、授权生命周期、过期时间和申请原因。
- [ ] 没有审批规则的 roles 或 permissions 不能提交。
- [ ] 提交后展示申请状态，并能区分 `submitted`、`approved`、`grant_applied`、`rejected` 和 `grant_failed`。
- [ ] 门户提交路径不会绕过 `AccessRequestService`，也不会直接创建 grant。

**验证：**

- [ ] 浏览器冒烟测试覆盖 app 选择、role 选择、生命周期校验和提交流程。
- [ ] `pytest tests/integration/portal`
- [ ] Playwright 冒烟覆盖提交路径。

**依赖：** 任务 11、任务 12、任务 13

**预计触达文件：**

- `src/easyauth/portal/views.py`
- `src/easyauth/portal/forms.py`
- `src/easyauth/portal/templates/`
- `tests/integration/portal/`

**预计规模：** 中

### 任务 15：发布试点接入包和端到端冒烟

**说明：** 输出试点接入文档，并建立端到端冒烟路径，证明 MVP 可以通过预期使用界面工作。

**验收标准：**

- [ ] 试点文档覆盖 static token 和 OAuth2 client credentials。
- [ ] 试点文档明确 Authentik UID 是 `user_id`。
- [ ] 试点文档包含权限查询端点、成功响应、空权限响应、错误码、缓存规则、version 语义、撤权 SLA 和 CRM 示例 roles/permissions。
- [ ] 端到端冒烟覆盖 Authentik 登录、CRM role 申请、模拟 DingTalk 审批、授权落库和 CRM 权限查询。

**验证：**

- [ ] Playwright 冒烟通过。
- [ ] `python manage.py check`
- [ ] `python manage.py migrate --check`
- [ ] `pytest`
- [ ] `ruff check .`
- [ ] `basedpyright`

**依赖：** 任务 7、任务 8、任务 12、任务 13、任务 14

**预计触达文件：**

- `docs/api/`
- `docs/pilot/`
- `tests/e2e/`

**预计规模：** 中

## 检查点：MVP 完成

- [ ] 试点内部应用收到凭据和文档后，可以在一个工作日内完成权限查询接入。
- [ ] static token 和 OAuth2 client credentials 产生完全一致的授权查询语义。
- [ ] 员工申请、DingTalk 审批、授权落库、撤权和过期行为都能通过测试和冒烟流程观察。
- [ ] 安全敏感事件写入 append-only 审计日志。
- [ ] 所有质量门槛通过。

## 可并行机会

- 任务 1 完成后，任务 2 和任务 3 可以并行推进，因为应用配置模型与用户/审计模型基本独立。
- 任务 7 稳定 API 认证行为后，任务 8 可以开始。
- 核心模型存在后，任务 9 和任务 10 可以并行。
- 任务 11 完成后，任务 12 可以推进；任务 13 可在任务 9 和任务 5 完成后与任务 12 并行。
- 任务 7 和任务 8 稳定后可以提前起草 API 文档，但任务 14 的员工门户前端必须等待任务 11、任务 12 和任务 13 完成。

## 必须顺序执行的工作

- 任务 1 必须最先完成，因为其他任务都依赖项目结构和工具链。
- 任务 5 必须先于任何修改 grants 的流程，因为 `GrantService` 是唯一授权写边界。
- 任务 7 应先于前端工作，因为 MVP 成功标准依赖内部应用授权查询接入。
- 任务 12 依赖任务 11 的申请创建能力和任务 5 的授权落库语义。
- 任务 14 不得早于任务 11、任务 12 和任务 13，除非只补齐 Authentik 会话边界、API 契约、测试夹具或文档草稿等必要例外。
- 任务 15 必须在任务 14 后执行，因为端到端冒烟需要真实员工门户表面。

## 风险和缓解措施

| 风险 | 影响 | 缓解措施 |
| --- | --- | --- |
| 试点应用接入后公共 API 契约变更 | 高 | 尽早稳定任务 7，并为响应结构、错误语义、version 和缓存行为添加集成测试。 |
| 前端过早开发导致后端契约返工 | 中 | 将员工门户固定为任务 14，只在后端闭环检查点通过后开发；提前工作仅限会话边界、API 契约和文档草稿。 |
| 开发期间缺少 Authentik 和 DingTalk 凭据 | 中 | 先基于类型化 payload 和 mock 构建适配器；真实凭据校验留到部署准备阶段。 |
| 撤权、过期和审批路径的 grant version 递增不一致 | 高 | 所有 grant 变更都经过 `GrantService`，并为每条变更路径测试旧/新 version 和审计事件。 |
| Admin 配置允许无效跨 app 规则 | 高 | 同时使用数据库约束和 Admin/form 校验。 |
| 回调重放导致重复应用授权 | 高 | 在回调事务中锁定 `AccessRequest`，并测试重复批准/拒绝回调。 |
| 客户端缓存权限超过授权生命周期 | 中 | 将 `expires_at` 计算为 app TTL 和最近 active grant 过期时间的较小值，并在文档中要求客户端不能自行延长。 |

## 开放问题

- 试点和生产环境的 Authentik issuer URL、client ID、client secret 和 callback URL 是什么？
- DingTalk app key 或 client ID、secret、agent ID 和 approval process code 是什么？
- CRM 试点 app owner 是谁？首批审批路由、roles、permissions 和 approvers 是什么？
- 生产域名、HTTPS 证书和网络访问策略是什么？
- 试点上线前需要满足什么审计日志保留周期和导出要求？

## 2026-06-06 当前进度快照

### 当前状态

- 状态：暂停，不能标记为完成。
- 本轮已按 TDD 推进 OPS-1、OPS-2、OPS-3 和 OPS-4 的后端能力，并使用多个子 Agent 并行完成实现、QA 和复审。
- QA 执行复审通过，但目标约束、安全、上下文契约和代码质量复审均发现阻塞项。
- 下一次继续开发时，应先处理下方阻塞项，再重新跑完整质量门和复审。

### 已实现范围

- OPS-1 管理端私有 API：App 列表与详情、配置状态、成员管理、审批规则、凭据管理、权限联调、权限模板预览与确认、模板版本、权限树、权限组、角色、权限、角色权限矩阵。
- OPS-2 门户 API：我的授权、即将过期授权、我的申请、直接权限申请、分页。
- OPS-3 运营 API：申请和授权列表筛选、失败授权重试、紧急撤权、依赖健康、审计查询。
- OPS-4 生命周期申请：change、revoke、renew 提交与审批后应用、DingTalk 模拟回调、回调签名、process instance ID 唯一约束、高风险角色续期最长时长策略。
- 安全/一致性修复：developer 写权限边界、矩阵保存原子性、retry 幂等、inactive role 公共权限查询过滤、审批应用阶段目标二次校验。

### 已通过验证

- `.venv/bin/ruff check .`
- `.venv/bin/basedpyright`
- `.venv/bin/python manage.py check`
- `.venv/bin/python manage.py makemigrations --check --dry-run`
- `.venv/bin/python manage.py migrate --check`
- `.venv/bin/pytest -q`，结果为 `346 passed`
- `git diff --check`
- Python 有效代码行扫描通过，单个 Python 文件未超过 250 pure LOC。
- QA 子 Agent 额外执行 OPS-1、OPS-2、OPS-3、OPS-4 聚焦测试和本地 HTTP 冒烟检查，未发现运行阻塞。

### 历史未完成或受阻事项（2026-06-06 复审前）

- in-app Browser 对 `http://127.0.0.1:8000/` 被 URL 策略阻止，未完成真实浏览器截图/交互冒烟检查。
- 下列契约差异和复审未通过结论为本轮恢复开发前的历史状态，已在 2026-06-06 恢复开发和最终复审中逐项处理。
- 当前状态以本文后续“2026-06-06 最终复审快照”为准。

### 历史优先阻塞项（已在 2026-06-06 恢复开发中处理）

1. OPS-1 API 契约对齐：
   - 补齐 `PATCH /permission-groups/{group_key}`、`PATCH /roles/{role_key}`、`PATCH /permissions/{permission_key}`。
   - 审批规则 API 支持 `target_type`/`target_key`，并支持 permission 目标规则创建、查询和更新。
   - 列表 API 与文档的分页和 `data + pagination` 响应结构对齐，或同步修订文档。
2. OPS-3 失败重试：
   - `grant_failed` 重试需要支持 change、revoke、renew，不能只走 `create_grant`。
   - 重试应复用审批应用语义，并补生命周期失败重试幂等测试。
3. 门户授权过滤：
   - `/portal/api/v1/me/grants` 需要过滤 inactive role 及其 role-derived permissions。
4. DingTalk 回调安全：
   - 签名校验增加 timestamp 新鲜度窗口，拒绝过旧和过未来回调。
   - approved 标记和授权应用需要更一致的事务边界，避免 rejected 回调覆盖 approved 但尚未应用完成的状态窗口。
5. 审批规则过期校验：
   - 应用阶段需要处理目标 ApprovalRule 被删除或改绑到其他目标后的“零规则”场景，必须进入 `grant_failed` 且不创建或变更授权。
6. 权限目录写接口质量：
   - 已废弃权限重新启用时，要清理 `deprecated_at`/`deprecated_reason`，或明确拒绝重新启用。
   - 权限组移动非叶子节点时，要递归更新子树 depth，或拒绝移动有子节点的组。
   - 权限矩阵乐观版本复核需放入事务或锁内，并补并发测试。
7. 文档契约差距：
   - AppMembership 写权限需与文档“仅系统管理员”对齐，或修订文档和需求。
   - 权限模板预览请求字段需要兼容 `format`/`content`，确认响应需要补齐文档字段。
   - 凭据禁用接口需要支持通用路径、禁用 reason 和 OAuth client 禁用。
   - 运营看板需要返回 DingTalk process instance、最近回调时间和处理结果；依赖健康检查是否审计需要与需求对齐。

### 下次继续建议

- 继续使用 TDD：每个阻塞项先补失败测试，再做最小修复。
- 优先处理安全阻塞项和文档契约阻塞项，再处理浏览器冒烟检查。
- 修复后重新运行完整质量门，并重新启动目标、代码质量、安全、QA、上下文五路复审。

## 2026-06-06 恢复开发完成快照

### 当前状态

- 状态：本轮恢复开发已完成实现、门禁和最终复审；按用户要求，更新本文档后暂停，等待下一步指令。
- 本轮继续使用 TDD 和并行子 Agent，已关闭完成或失效的子 Agent；当前不保留未使用后台任务。
- 未执行提交、推送或发布动作。

### 本轮已完成修复

- 门户授权列表过滤 inactive Role 及其 role-derived permissions，避免 `/portal/api/v1/me/grants` 泄漏已停用角色权限。
- DingTalk callback 签名增加 timestamp 新鲜度校验，并防止迟到 rejected callback 覆盖已经进入 approved、grant_applied 或 grant_failed 的申请状态。
- 审批应用阶段补齐目标二次校验：change、revoke、renew 的 Role/Permission 被停用、审批规则被删除或改绑后，申请进入 `grant_failed` 且不变更授权事实。
- `grant_failed` retry 支持 change、revoke、renew；retry 前 lifecycle 目标已失效时返回语义错误并保持授权事实不变，同时保持 `grant_applied` 重复 retry 幂等。
- Admin Console 契约补齐：
  - list 响应兼容 `items` 与 `data`。
  - AppMembership 写入改为 sysadmin-only。
  - 权限模板 preview 支持 `format`/`content`，同时保留旧字段兼容。
  - 通用 credentials disable 支持 static token 与 OAuth client，并记录 reason。
  - catalog 支持 key-based PATCH route。
  - App list 支持 `page`、`page_size`、`status`、`owner_user_id` 与 `pagination`，并保留 `items`/`data` 兼容。
  - App detail 返回负责人、开发者、Role/Permission 数量、active 凭据数量、最新模板版本和配置摘要。
  - ApprovalRule 支持 `target_type`/`target_key`，包括 permission target。
  - operations access-requests 返回 DingTalk process 与 callback 兼容字段。
  - dependency-health 返回 list 与顶层依赖 map 兼容字段，并写入读取审计。
  - retry-grant 响应补齐 `request_id`，emergency revoke 响应补齐 `status: accepted`。
  - OAuth client 通用禁用接口保持历史 binding 和 OAuth application，仅标记 inactive 并记录 reason。
  - RolePermission matrix 兼容 `permission_tree`、key-based `assignments`、`base_version`、`add`/`remove`，并同时记录 `role_permission_matrix_changed` 审计事件。
- 权限目录质量修复：
  - deprecated Permission 拒绝直接重新启用，避免 console 与 runtime 查询状态漂移。
  - `deprecated_reason` 与 `is_active=true` 同请求时最终仍强制 inactive，matrix 也拒绝 active 但已 deprecated 的 Permission。
  - PermissionGroup 移动后递归更新子树 depth。
  - PermissionGroup 移动若后代 depth 更新失败，会在事务中回滚已移动节点和后代，避免 422 后部分落库。
  - RolePermission matrix 在事务内锁定并复核版本。
  - permission tree 的 `children` 兼容 permission 节点，同时保留旧 `permissions` 字段。
- Portal 分页响应补齐 `data` 字段，与 `items` 保持兼容。
- API 文档中 RolePermission matrix 的 `version`/`base_version` 示例已改为字符串，匹配当前 hash 版本实现。

### 已通过验证

- `.venv/bin/ruff check .`：通过。
- `.venv/bin/basedpyright`：`0 errors, 0 warnings, 0 notes`。
- `.venv/bin/python manage.py check`：通过。
- `.venv/bin/python manage.py makemigrations --check --dry-run`：`No changes detected`。
- `.venv/bin/python manage.py migrate --check`：通过。
- `git diff --check`：通过。
- Python pure LOC 扫描：未发现超过 250 行的非 migration Python 文件。
- `.venv/bin/pytest -q`：`396 passed`。
- 受影响 Admin Console focused suite：`49 passed`；本次 lifecycle/retry focused suite：`79 passed`。
- 五路最终复审曾发现 PermissionGroup 移动回滚和 renew/revoke stale target 缺口；两项均已按 TDD 补回归测试并修复。

### 仍需说明的限制

- 本线程此前尝试 in-app Browser 打开 `http://127.0.0.1:8000/` 被 URL 策略阻止；本轮未重新尝试 localhost/127.0.0.1 浏览器冒烟。当前可用证据来自 HTTP/API 测试、Django 检查和 pytest 行为测试。
- 仍未执行真实 DingTalk、真实 Authentik 或生产环境联调；当前覆盖基于本地模型、mock callback 和集成测试。

### 后续建议

- 若继续推进 MVP，应优先补试点接入文档和可运行的端到端冒烟入口。
- 若环境允许访问本地浏览器目标，再补员工门户真实浏览器交互截图/冒烟记录。

## 2026-06-06 最终复审快照

### 当前结论

- 实现契约无新增阻塞；后续目标/安全复审指出的 renew/revoke stale target 缺口已修复并通过回归测试。
- 质量门禁最新结果：`ruff` 通过、`basedpyright` 0 errors、Django check/migration/diff check 通过、全量 pytest `396 passed`。
- 已关闭当前任务使用的子 Agent；未执行提交、推送或发布。

### 最终补齐项

- App list/detail、配置完整性、permission tree、permission group/permission key-based payload、RolePermission matrix 主要文档契约已实现或兼容。
- RolePermission matrix 文档示例的 `version`/`base_version` 已改为字符串，避免调用方按数字版本提交。
- PermissionGroup 移动失败回滚已补测试，避免返回 422 时留下 parent/depth 部分更新。
- renew/revoke 审批应用和 retry-grant 均会重验保留或续期目标，避免 stale Role/Permission 或 stale ApprovalRule 继续改写授权事实。

### 剩余限制

- 本线程仍未完成真实浏览器冒烟；此前 in-app Browser 对 `http://127.0.0.1:8000/` 被 URL 策略阻止。
- 仍未执行真实 DingTalk、真实 Authentik 或生产环境联调。
