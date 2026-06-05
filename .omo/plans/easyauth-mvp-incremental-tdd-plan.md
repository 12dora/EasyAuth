# EasyAuth MVP 增量 TDD 执行计划

## 摘要

> **目标**：从当前只有文档的仓库开始，按小垂直切片实现 EasyAuth MVP，让试点内部应用可以通过稳定 API 查询授权，并覆盖申请、审批、撤权、过期和试点接入文档。
> **交付物**：Django 模块化单体、领域模型与服务、`/api/v1` 权限查询、静态 token、OAuth2 client credentials、Authentik 同步与登录边界、员工门户、DingTalk 模拟审批回调、撤权过期任务、试点文档、端到端冒烟。
> **规模**：大。
> **并行**：是，4 个主要并行波次。第一切片单独执行，之后按模块所有权拆给子代理。
> **关键路径**：S1 工程基线 -> S5 授权模型 -> S6 GrantService -> S8 权限查询 API -> S13 申请门户 -> S14 DingTalk 回调 -> S16 端到端冒烟。

## 上下文

### 原始请求

用户要求阅读已补齐文档并列出计划。此前明确要求执行时使用子代理尽量并行，采用 `incremental-implementation` 与 `test-driven-development`，不要一次性实现全部需求，每个切片先写或更新测试，看到失败后再实现，完成后运行相关测试并总结。

### 已阅读文档

- `AGENTS.md`：项目文档必须使用中文。
- `docs/README.md`：当前实现、评审和试点接入以架构设计文档为准。
- `docs/architecture/easyauth-architecture-design.md`：EasyAuth 当前有效架构、API 契约、服务边界、安全规则和测试策略。
- `docs/plans/easyauth-mvp-implementation-plan.md`：MVP 初始实施顺序、依赖、验收、风险和开放问题。

### Metis 审查已处理缺口

- 增加 API 契约优先切片，避免先实现接口后补契约。
- 增加本地基础设施和测试数据库策略，避免集成测试不可运行。
- 固化工具链默认值：Python 3.12、Django 5.2 LTS、uv、pytest-django、ruff、basedpyright。
- 固化 `ApprovalRule` MVP 审批人策略：显式 DingTalk userid 列表，不实现 manager chain。
- 固化 `AccessGrant` 当前行语义：每个 user/app 一条当前授权行，历史通过 `AccessRequest`、`AuditLog` 和 version 追踪。
- 固化 OAuth 错误边界：`/oauth/token` 保持 OAuth2 标准错误，`/api/v1` 使用 EasyAuth 统一错误格式。
- 区分本地模拟端到端验证与真实外部集成冒烟；真实凭据不是本地开发阻塞项。

## 工作目标

### 核心目标

实现 EasyAuth MVP，使内部应用可以用静态 app token 或 OAuth2 client credentials 查询某 Authentik UID 在指定 App 下的 roles、permissions、version 和缓存 `expires_at`，并能通过员工申请、DingTalk 模拟审批、GrantService 授权落库、撤权和过期流程观察到一致结果。

### 必须有

- Authentik 是身份和在职状态权威来源。
- DingTalk 只提供审批流程证据，不直接授予权限。
- EasyAuth 是授权事实来源。
- 公共 `user_id` 使用 Authentik UID/OIDC subject。
- 静态 app token 与 OAuth2 client credentials 的权限查询 JSON 响应在冻结时间下完全一致。
- 所有安全敏感事件写入只追加 `AuditLog`。
- 所有 `/api/v1` 响应使用统一错误结构。
- 每个实现切片先 RED 后 GREEN，再运行相关测试。

### 不做

- 多租户 SaaS、完整 IAM、ABAC、行级或字段级权限、AI 权限推荐、复杂权限复制、所有权交接、未经审批授权。
- 真实生产部署密钥配置。
- 未经用户明确要求不自动提交 git commit；执行时每个切片输出改动和测试结果。

## 验证策略

- 测试决策：TDD，使用 pytest、pytest-django、DRF APIClient、Playwright。
- 每个切片必须先新增或更新一个会失败的测试，记录失败命令，再实现代码让测试通过。
- 每个切片完成后运行该切片的相关测试；影响公共契约、模型或 settings 时同步运行 `python manage.py check`、`ruff check .`、`basedpyright`。
- 执行代理为每个切片保存证据到 `.omo/evidence/task-S{N}-{slug}.txt` 或 `.png`。
- 本地集成默认通过 Docker Compose 提供 PostgreSQL 16 和 Redis；Celery 测试默认 eager 模式。

## 并行执行波次

- 第 1 波：S1 由单个执行代理拥有工程骨架和工具链，避免共享文件冲突。
- 第 2 波：S2、S3、S4 可并行；分别拥有 applications、accounts/audit、API 契约。
- 第 3 波：S5、S7、S10 可在依赖满足后并行；S6 是权限写边界关键路径。
- 第 4 波：S8、S9、S11、S12、S15 分模块推进；S13 和 S14 继续关键路径。
- 最终波：S16 和最终验证。

## 依赖矩阵

| 切片 | 依赖 | 主要阻塞 |
| --- | --- | --- |
| S1 | 无 | 全部后续任务 |
| S2 | S1 | S5、S7、S11 |
| S3 | S1 | S5、S10、S11 |
| S4 | S1 | S8、S16 |
| S5 | S2、S3 | S6、S13 |
| S6 | S5 | S8、S10、S14、S15 |
| S7 | S2 | S8、S9 |
| S8 | S4、S6、S7 | S9、S16 |
| S9 | S8 | S16 |
| S10 | S3、S6 | S13、S15、S16 |
| S11 | S2、S3、S5、S7 | S13、S16 |
| S12 | S3、S10 | S13、S16 |
| S13 | S5、S11、S12 | S14、S16 |
| S14 | S6、S13 | S16 |
| S15 | S6、S10 | S16 |
| S16 | S8、S9、S14、S15 | 最终验收 |

## 待办切片

### S1. 初始化 Django 工程、工具链和本地基础设施

**所有权**：单个执行子代理，负责 `pyproject.toml`、`manage.py`、`src/easyauth/config/`、`tests/`、Docker Compose、质量命令。

**TDD 步骤**：先写 pytest 冒烟测试，断言 Django settings 可加载、`manage.py check` 可运行；确认失败后初始化项目和依赖。

**验收标准**：

- `src/easyauth/`、`manage.py`、settings、URLs、ASGI、WSGI、测试目录存在。
- `pyproject.toml` 声明 Python 3.12、Django 5.2 LTS、DRF、PostgreSQL driver、Redis、Celery、Django OAuth Toolkit、pytest、ruff、basedpyright。
- Docker Compose 提供 PostgreSQL 16 和 Redis；测试 settings 支持 Celery eager。

**验证**：`python manage.py check`、`pytest`、`ruff check .`、`basedpyright`。

### S2. 实现 App、Role、Permission、ApprovalRule 配置模型

**所有权**：执行子代理拥有 `src/easyauth/applications/` 和 `tests/unit/applications/`。

**TDD 步骤**：先写模型约束测试，覆盖重复 app key、同 app 内 role/permission key 重复、跨 app RolePermission、ApprovalRule 目标互斥和审批人 userid 列表校验；确认失败后实现模型和迁移。

**验收标准**：

- `App.app_key` 唯一且稳定。
- `Role.key`、`Permission.key` 在同一 app 内唯一。
- `RolePermission` 禁止跨 app。
- `ApprovalRule` 有且仅有一个 role 或 permission 目标，并保存非空 DingTalk approver userid 列表。

**验证**：`pytest tests/unit/applications`、`python manage.py makemigrations --check`、`python manage.py migrate --check`。

### S3. 实现 UserMirror 和 AuditLog

**所有权**：执行子代理拥有 `src/easyauth/accounts/`、`src/easyauth/audit/` 和对应测试。

**TDD 步骤**：先写测试覆盖 Authentik UID 唯一、状态枚举、审计写入、审计更新和删除被拒绝；确认失败后实现模型、服务和 Admin 只读保护。

**验收标准**：

- `UserMirror.authentik_user_id` 全局唯一且不物理删除。
- `UserMirror.status` 支持 `active`、`disabled`、`departed`。
- `AuditService.record()` 是默认写入口。
- `AuditLog` 应用层只追加，Admin 中不可编辑和删除。

**验证**：`pytest tests/unit/accounts tests/unit/audit tests/integration/admin`。

### S4. 建立 `/api/v1` 契约、错误码和 schema 测试

**所有权**：执行子代理拥有 `src/easyauth/api/` 的契约层、OpenAPI/schema 文件和 `tests/integration/api/` 契约测试。

**TDD 步骤**：先写 schema/serializer 测试，断言统一错误结构、权限查询响应字段、分页默认规则和错误 code 枚举；确认失败后实现契约骨架。

**验收标准**：

- `/api/v1` 错误结构固定为 `{"error": {"code", "message", "details"}}`。
- 明确错误码：`VALIDATION_ERROR`、`AUTHENTICATION_FAILED`、`PERMISSION_DENIED`、`NOT_FOUND`、`CONFLICT`、`SEMANTIC_VALIDATION_ERROR`、`INTERNAL_ERROR`。
- 权限查询响应契约包含 `user_id`、`app_key`、`roles`、`permissions`、`version`、`expires_at`。

**验证**：`pytest tests/integration/api/test_contract.py`。

### S5. 实现 AccessRequest 和 AccessGrant 模型

**所有权**：执行子代理拥有 `src/easyauth/access_requests/`、`src/easyauth/grants/models.py` 和对应测试。

**TDD 步骤**：先写生命周期、状态机、唯一当前授权、timed/permanent 约束和跨 app 授权子表测试；确认失败后实现模型和迁移。

**验收标准**：

- `AccessRequest` 支持 `grant`、`change`、`revoke`。
- `approved` 与 `grant_applied` 是分离状态。
- timed 授权必须有 `grant_expires_at`，permanent 必须为空。
- 每个 user/app 最多一条当前 `AccessGrant` 行。
- 授权 role 和直接 permission 必须属于同一 app。

**验证**：`pytest tests/unit/access_requests tests/unit/grants`、`python manage.py makemigrations --check`、`python manage.py migrate --check`。

### S6. 实现 GrantService 授权写边界和权限解析

**所有权**：执行子代理拥有 `src/easyauth/grants/services.py`、`src/easyauth/grants/query.py` 和 `tests/unit/grants/`。

**TDD 步骤**：先写 RED 测试覆盖 create/change/revoke/expire 的 version 递增、角色展开权限、稳定排序、disabled/departed/revoked/expired 空权限、审计事件；确认失败后实现服务。

**验收标准**：

- 所有 grant 变更只通过 `GrantService`。
- 每次创建、变更、撤销、过期都递增 version。
- roles 和 permissions 按 key 升序。
- 非 active 用户或授权不产生 active permissions。
- 并发变更使用事务锁，重复 revoke/expire 幂等。

**验证**：`pytest tests/unit/grants`。

### S7. 实现静态 app token 和 AppPrincipal

**所有权**：执行子代理拥有 `src/easyauth/applications/services.py`、`src/easyauth/api/authentication.py` 和相关测试。

**TDD 步骤**：先写 token 创建、hash 存储、一次性明文、禁用、轮换、无效 token、disabled app 的失败测试；确认失败后实现凭据模型和 DRF authentication。

**验收标准**：

- token 有前缀、足够熵，只展示一次明文。
- 数据库只保存 hash。
- 已禁用 token 和已禁用 app 认证失败。
- 认证成功输出 `AppPrincipal(app_id, app_key, credential_type, credential_id)`。

**验证**：`pytest tests/unit/applications tests/integration/api/test_authentication.py`。

### S8. 实现静态 token 权限查询 API

**所有权**：执行子代理拥有 `src/easyauth/api/views.py`、`serializers.py`、`urls.py`、`tests/integration/api/test_permission_query.py`。

**TDD 步骤**：先写集成测试覆盖 active、empty、unknown user、disabled/departed user、revoked、expired、cross-app、disabled app、稳定排序、expires_at min TTL；确认失败后实现端点。

**验收标准**：

- `GET /api/v1/apps/{app_key}/users/{user_id}/permissions` 可用。
- 路径 app_key 与 `AppPrincipal.app_key` 不一致返回 403。
- 用户不存在、disabled、departed 返回空 roles/permissions，不暴露存在性。
- 无历史授权 unknown user 返回 `version: 0`。
- 成功查询写入 `app_permission_queried` 审计事件。

**验证**：`pytest tests/integration/api/test_permission_query.py`，使用 CRM 种子数据和 `curl` 保存手动证据。

### S9. 实现 OAuth2 client credentials 绑定与响应等价

**所有权**：执行子代理拥有 `src/easyauth/applications/oauth.py`、`src/easyauth/api/authentication.py`、OAuth URLs 和 `tests/integration/oauth/`。

**TDD 步骤**：先写 token 签发、client 精确绑定 app、invalid token、disabled app、静态 token 与 OAuth 响应等价测试；确认失败后接入 Django OAuth Toolkit。

**验收标准**：

- OAuth client 精确绑定一个 `App`。
- `/oauth/token` 可签发 client credentials access token。
- `/oauth/token` 错误保持 OAuth2 标准；后续 `/api/v1` 错误保持 EasyAuth 统一结构。
- 同一 app/user 在冻结时间下，OAuth 与静态 token 查询 JSON 完全一致。

**验证**：`pytest tests/integration/oauth tests/integration/api/test_permission_query.py`，`curl /oauth/token` 和权限查询。

### S10. 实现 Authentik 用户同步和离职撤权

**所有权**：执行子代理拥有 `src/easyauth/integrations/authentik/`、`src/easyauth/accounts/services.py`、`src/easyauth/tasks/authentik.py`。

**TDD 步骤**：先写 payload 解析、状态映射、webhook upsert、定时同步入口、inactive/disabled/departed 撤权测试；确认失败后实现适配器和服务。

**验收标准**：

- Authentik OIDC subject 映射为 `authentik_user_id`。
- webhook 和定时同步都能 upsert。
- 非 active 状态触发所有 active grants revoke、version 递增和审计。
- 没有真实 Authentik 凭据时使用测试夹具 payload 和模拟 client 验证。

**验证**：`pytest tests/unit/integrations/authentik tests/integration/authentik tests/unit/grants`。

### S11. 强化 Django Admin 和 CRM 种子数据

**所有权**：执行子代理拥有各 app 的 `admin.py`、测试夹具、management command 和 `tests/integration/admin/`。

**TDD 步骤**：先写 Admin 表单和种子数据测试，覆盖 token 明文不展示、AuditLog 只读、ApprovalRule 校验、缺审批规则的 requestable role 标记无效；确认失败后实现 Admin 和 CRM 种子数据。

**验收标准**：

- 空库可创建或导入 CRM App、Role、Permission、RolePermission、ApprovalRule、AppCredential。
- 敏感字段不出现在列表、详情、日志或审计视图。
- Admin 不绕过领域校验。

**验证**：`pytest tests/integration/admin`，手动 Admin 冒烟保存证据。

### S12. 实现 Authentik OIDC 登录和门户 session 边界

**所有权**：执行子代理拥有 `src/easyauth/accounts/auth.py`、登录 URLs、portal auth middleware/tests。

**TDD 步骤**：先写 OIDC callback token 校验、issuer/audience/redirect URI 校验、session user 绑定、测试专用 authenticated user 测试夹具测试；确认失败后实现登录边界。

**验收标准**：

- 员工门户依赖 Authentik session。
- OIDC callback 只接受配置的 issuer、audience、redirect URI。
- 本地测试可以通过模拟 OIDC payload 建立 session。
- 管理端 MVP 仍可使用 Django superuser bootstrap；EasyAuth admin role 后续复用服务层，不由 DingTalk 授予。

**验证**：`pytest tests/integration/auth tests/integration/portal`。

### S13. 实现员工访问申请服务和门户

**所有权**：执行子代理拥有 `src/easyauth/access_requests/services.py`、`src/easyauth/portal/` 和 portal 测试。

**TDD 步骤**：先写服务和浏览器测试，覆盖 app 选择、requestable role、审批规则缺失拒绝、timed/permanent 校验、提交后状态和审计；确认失败后实现 SSR + HTMX 门户。

**验收标准**：

- 员工可选择 App、role、有效期、过期时间和原因。
- 没有审批规则的 role/permission 不能提交。
- 提交写入 `access_request_submitted`。
- 提交后创建 `AccessRequest`，但不直接创建 grant。

**验证**：`pytest tests/unit/access_requests tests/integration/portal`，Playwright 冒烟覆盖提交路径。

### S14. 实现 DingTalk 审批创建、回调和授权落库

**所有权**：执行子代理拥有 `src/easyauth/integrations/dingtalk/`、`src/easyauth/access_requests/callbacks.py` 和 `tests/integration/dingtalk/`。

**TDD 步骤**：先写模拟 gateway、payload 测试夹具、签名校验、approved/rejected、重复 approved/rejected、unknown process、invalid signature、grant failure 测试；确认失败后实现回调服务。

**验收标准**：

- 提交申请创建模拟 DingTalk process instance 并保存唯一 ID。
- 回调校验签名、process ID、payload 和当前状态。
- approved 通过 `GrantService.apply_approved_request()` 落库。
- 重复回调幂等，不重复递增 version。
- 授权落库失败进入 `grant_failed` 并写入 `grant_apply_failed`。

**验证**：`pytest tests/unit/integrations/dingtalk tests/integration/dingtalk tests/unit/grants`，使用真实 callback 端点的模拟请求保存证据。

### S15. 实现授权过期清理和紧急撤权

**所有权**：执行子代理拥有 `src/easyauth/tasks/grants.py`、`src/easyauth/admin_console/`、`src/easyauth/grants/services.py` 扩展和测试。

**TDD 步骤**：先写 timed grant 到期、重复清理、并发跳过、紧急撤权只能减少权限、撤权后 API 空权限测试；确认失败后实现任务和受控入口。

**验收标准**：

- Celery beat 扫描到期 active timed grants。
- 到期授权转 revoked、递增 version、写入 `grant_expired`。
- 紧急撤权不能授予或增加权限。
- 清理和撤权幂等。

**验证**：`pytest tests/unit/grants tests/integration/api`。

### S16. 发布试点接入文档和端到端冒烟

**所有权**：执行子代理拥有 `docs/api/`、`docs/pilot/`、`tests/e2e/` 和 Playwright 测试框架。

**TDD 步骤**：先写端到端冒烟脚本或测试，覆盖模拟 Authentik 登录、CRM role 申请、模拟 DingTalk approval、grant application、静态 token 和 OAuth 查询；确认失败后补齐种子数据、文档和测试框架。

**验收标准**：

- 中文试点文档覆盖 static token、OAuth2 client credentials、Authentik UID、权限查询端点、成功响应、空权限响应、错误码、缓存规则、version 语义、撤权 SLA、CRM 示例 roles/permissions。
- 端到端冒烟证明完整本地路径可用。
- 文档说明真实试点部署前需要补齐 Authentik、DingTalk、域名、网络和审计保留输入。

**验证**：`pytest tests/e2e` 或 Playwright 冒烟、`python manage.py check`、`python manage.py migrate --check`、`pytest`、`ruff check .`、`basedpyright`。

## 最终验证波次

- F1 计划一致性审查：确认每个 docs 要求都有实现或明确非目标。
- F2 代码质量审查：检查服务边界、事务、类型、错误语义和安全敏感路径。
- F3 手动表面 QA：通过浏览器走门户申请，通过 `curl` 查询静态 token 和 OAuth 权限。
- F4 范围审查：确认没有实现非目标，没有绕过 Authentik/DingTalk/EasyAuth 的权威边界。

## 成功标准

- 所有切片的相关测试通过。
- `python manage.py check`、`python manage.py migrate --check`、`pytest`、`ruff check .`、`basedpyright` 通过。
- 静态 app token 与 OAuth2 client credentials 对同一 app/user 返回一致权限查询响应。
- 本地模拟端到端流程可以观察：登录 -> 申请 CRM role -> DingTalk 模拟批准 -> grant 落库 -> CRM 权限查询变化 -> revoke/expiry 后空权限。
- 试点接入文档足以让内部应用基于示例 token/client、curl 和 OpenAPI 代理验证接入路径。

## 执行汇报格式

每完成一个切片，执行代理必须汇报：

- 切片编号和范围。
- RED 测试：新增/更新了什么测试，失败命令和失败原因。
- GREEN 实现：改了哪些文件，为什么是最小实现。
- 验证结果：运行了哪些命令，结果是什么。
- 后续阻塞或并行机会。
