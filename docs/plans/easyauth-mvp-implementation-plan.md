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

## 阶段 1：基础建设

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

## 阶段 2：第一条可用授权查询 API

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

## 阶段 3：身份、审批和后端运营能力

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

## 阶段 4：前端和试点接入包

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
