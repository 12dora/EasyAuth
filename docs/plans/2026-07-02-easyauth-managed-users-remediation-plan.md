# EasyAuth MANAGED_USERS 改造方案

## 背景

本方案基于 `docs/architecture/easyauth-managed-users-upstream-downstream-design.md` 中的 EasyAuth 改造部分，并结合四个子代理对后端模型、后端接口、前端契约、测试与文档的只读探索结果。

EasyAuth 当前已经具备 App、Scope、Permission、AuthorizationGroup、AccessGrant、公共权限查询、员工门户申请、控制台配置和 Authentik DingTalk 目录同步基础能力。但当前授权范围仍只是静态 `scope_key`，无法表达“当前用户可管理的下级 active Authentik 用户集合”。本次改造的核心是把 `MANAGED_USERS` 做成按 App、Permission、Grant 解析的业务授权结果，而不是用户的全局静态属性。

## 目标

- 在 EasyAuth 引入 `MANAGED_USERS` scope 语义，表示当前用户可管理的下级 active Authentik 用户 ID 集合。
- 支持 App 默认管理范围策略，以及 `AuthorizationGroupGrant` 单独覆盖策略。
- 公共权限查询在 `MANAGED_USERS` grant 上返回 `resolved.user_ids`、`resolver`、`resolved_at`。
- 控制台提供图形化策略配置、有效策略展示、健康状态和预览能力。
- 员工自助申请包含 `MANAGED_USERS` grant 时，默认审批人取申请人的直属上级；找不到直属上级时留空并要求用户补全。
- 统一试点数据、manifest、测试和文档里的管理范围命名为 `MANAGED_USERS`，不保留旧 `MANAGED` 兼容口径。

## 非目标

- 不在 EasyAuth 第一版实现通用 ABAC 或行级策略引擎。
- 不让下游应用实时调用 EasyAuth 查询业务过滤条件。
- 不在 EasyAuth 本轮实现 EasyTrade 本地快照过滤逻辑。
- 不把 DingTalk 原始目录字段直接暴露给下游应用。
- 不新增旧 scope 名称、旧响应字段或静默转换层。

## 总体设计

`MANAGED_USERS` 的生效链路如下：

```text
AccessGrant
  -> AuthorizationGroupGrant(permission, scope=MANAGED_USERS)
  -> ManagedScopePolicy(app 默认或 grant 覆盖)
  -> ManagedUsersResolver(dingtalk_manager_chain)
  -> active Authentik user_ids
  -> 公共权限查询 grants[].resolved
```

关键原则：

- `MANAGED_USERS` 只对 scope 为 `MANAGED_USERS` 的 grant 触发解析。
- 普通 scope 的 grant 保持现有四元组响应，不带 `resolved`。
- 单个 grant 有覆盖策略时优先使用覆盖策略；没有覆盖策略时继承 App 默认策略。
- 没有有效策略时，该 `MANAGED_USERS` grant 不生效，不能返回空 resolved 冒充成功。
- 策略有效且解析结果为空时，保留 grant，并返回 `resolved.user_ids=[]`。
- 解析出的 `user_ids` 只包含 active Authentik 用户 ID，不包含当前用户本人。
- 目录源不可用、无有效快照、用户缺少 DingTalk 绑定、映射不唯一等情况必须进入健康检查、预览和审计日志，不能静默放权或降级成功。

## 组件拆分

### 1. 策略模型与领域服务

新增 `ManagedScopePolicy`，建议放在 `src/easyauth/applications/models.py` 或拆到 `src/easyauth/applications/managed_scope_models.py` 后由 `applications.models` 导出。字段：

- `app`
- `target_type`: `app_default` 或 `authorization_group_grant`
- `target_id`: App 默认策略使用 `app.id`，grant 覆盖策略使用 `AuthorizationGroupGrant.id`
- `scope`: 第一版固定 `MANAGED_USERS`
- `resolver`: `dingtalk_manager_chain` 或 `disabled`
- `enabled`
- `created_at`
- `updated_at`

约束：

- `(app, target_type, target_id, scope)` 唯一。
- `scope` 第一版只能是 `MANAGED_USERS`。
- `resolver` 只能是 `dingtalk_manager_chain` 或 `disabled`。
- `target_type=authorization_group_grant` 时必须确认 `target_id` 指向同 App 的 `AuthorizationGroupGrant`。
- `resolver=disabled` 或 `enabled=false` 都不能让相关 grant 成为有效授权。

新增服务模块建议：

- `src/easyauth/applications/managed_scope_policy.py`
  - 读取 App 默认策略。
  - 读取 grant 覆盖策略。
  - 计算有效策略和继承来源。
  - 提供控制台保存入口。
- `src/easyauth/grants/managed_users.py`
  - 执行 `MANAGED_USERS` 解析。
  - 返回 resolved 结构和诊断信息。
  - 统一处理无策略、disabled、无绑定、目录 stale、无有效快照、inactive 或未绑定用户等分支。

### 2. DingTalk 管理对象解析

第一版 EasyAuth 应优先消费 Authentik 新增的归一化管理对象接口：

```http
GET /api/v3/sources/oauth/dingtalk-directory/{source_slug}/managed-users/by-manager/{corp_id}/{manager_user_id}/
```

EasyAuth 侧改造：

- 在 `src/easyauth/integrations/authentik/directory_payloads.py` 增加 managed users payload dataclass 与 parser。
- 在 `src/easyauth/integrations/authentik/directory_client.py` 增加 `get_managed_users(corp_id, manager_user_id)`。
- 在 `tests/integration/authentik/test_directory_client.py` 覆盖成功响应、403/404、无效 JSON、字段缺失、inactive 和未绑定人员解析。
- 在 `src/easyauth/grants/managed_users.py` 中只接收 parser 后的稳定结构，不让公共权限查询直接读原始 DingTalk 字段。

短期本地递归计算只作为明确标注的替代实施路径，不能和上游接口并行长期存在。若采用本地递归，必须先补齐 `DingTalkUserMirror` 到 `UserMirror.authentik_user_id` 的唯一映射能力、目录版本和最后有效快照语义。

### 3. 公共权限查询契约

修改文件：

- `src/easyauth/grants/query.py`
- `src/easyauth/api/serializers.py`
- `src/easyauth/api/views.py`
- `src/easyauth/admin_console/query_tester.py`
- `src/easyauth/admin_console/query_test_api.py`
- `src/easyauth/portal/api_data.py`
- `src/easyauth/portal/permission_aggregation.py`

领域类型调整：

- `ExpandedGrant` 增加可选 `resolved`。
- 新增 `ResolvedManagedUsers`，字段为 `user_ids`、`resolver`、`resolved_at`。
- `PermissionSnapshot` 保持现有版本字段，但 snapshot 里的 grant 需要包含 resolved。

响应规则：

- 普通 grant：

```json
{
  "permission": "trade.order.read",
  "scope": "GLOBAL",
  "source_type": "group",
  "source_key": "trade_admin"
}
```

- `MANAGED_USERS` grant：

```json
{
  "permission": "trade.order.read",
  "scope": "MANAGED_USERS",
  "source_type": "group",
  "source_key": "trade_manager",
  "resolved": {
    "user_ids": ["ak_uid_001", "ak_uid_002"],
    "resolver": "dingtalk_manager_chain",
    "resolved_at": "2026-07-02T12:00:00+08:00"
  }
}
```

失败规则：

- 无有效策略：不返回该 `MANAGED_USERS` grant，并记录诊断。
- 用户缺少 DingTalk 绑定：不返回该 grant，并记录诊断。
- 无任何有效组织快照：不返回该 grant，并记录诊断。
- 策略有效但下级为空：返回 grant，`resolved.user_ids=[]`。
- 解析异常：不返回该 grant，健康检查、预览和审计必须可见。

### 4. 控制台配置与预览

后端 API 改造：

- `src/easyauth/admin_console/authorization_groups_api.py`
  - grant payload 增加 `managed_scope_policy`。
  - 更新授权组时，在同一事务保存 grant 与其覆盖策略。
  - 删除或停用 grant 时不得留下有效孤儿策略。
- `src/easyauth/admin_console/permission_catalog_data.py`
  - authorization group grant item 返回策略配置、有效策略、继承来源和健康状态。
- 新增 App 级管理范围策略 API，建议路径：
  - `GET/PATCH /console/api/v1/apps/{app_key}/managed-scope-policy`
- 新增预览 API，建议路径：
  - `POST /console/api/v1/apps/{app_key}/managed-users-preview`

控制台文案：

- App 级页面：“管理范围计算方式”
  - `按钉钉主管关系`
  - `不启用`
- Grant 行：“管理范围计算方式”
  - `继承应用默认`
  - `按钉钉主管关系`
  - `不启用`
- 无有效策略时提示：“必须配置管理范围计算方式后才能生效”。

前端改造：

- `frontend/src/lib/domain.ts`
  - 增加 `ManagedScopePolicyItem`、`EffectiveManagedScopePolicyItem`、`ResolvedManagedUsers`。
  - `ExpandedGrantItem` 增加可选 `resolved`。
  - `AuthorizationGroupGrantItem` 增加策略字段。
- `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
  - 在 grant 表格和编辑表单增加策略选择、有效策略、继承来源和健康状态。
- `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx`
  - 展示 `resolved.user_ids` 数量、resolver、resolved_at，并支持空数组可见。
- `frontend/src/pages/console/ConsoleAppWorkspace.tsx`
  - 增加 App 默认策略入口；如页面过大，可新增一个“管理范围”tab，但不再拆分到多个碎片页面。

### 5. 健康检查与审计

改造文件：

- `src/easyauth/applications/configuration.py`
- `src/easyauth/applications/dependency_health.py`
- `src/easyauth/admin_console/apps_api.py`
- `src/easyauth/admin_console/operations_api.py`
- `src/easyauth/audit/services.py` 的调用点

健康检查至少输出：

- `managed_scope_app_default_policy_missing`
- `managed_scope_grant_policy_missing`
- `managed_scope_policy_disabled`
- `managed_scope_directory_unavailable`
- `managed_scope_directory_stale`
- `managed_scope_user_dingtalk_binding_missing`
- `managed_scope_resolved_user_unbound`
- `managed_scope_resolved_user_inactive`

检查层级：

- App 配置健康：检查 App 下含 `MANAGED_USERS` 的 active grant 是否能获得有效策略。
- 预览健康：针对用户、App、授权组或 grant 输出真实解析结果和失败原因。
- 依赖健康：继续展示 Authentik Directory、DingTalk、Celery 等基础依赖状态，但不要把依赖健康当成 managed scope 配置健康的替代。

审计建议事件：

- `managed_scope_policy_updated`
- `managed_users_preview_executed`
- `managed_users_resolution_failed`
- `managed_users_resolution_succeeded`

审计 metadata 只能记录必要的 app、group、permission、scope、resolver、计数和错误码，不记录敏感 token。

### 6. 自助申请

后端改造：

- `src/easyauth/portal/request_catalog.py`
  - 当 requestable authorization group 或 direct grant 包含 `MANAGED_USERS` 时，默认审批人取申请人的直属上级。
  - 找不到 active EasyAuth 用户形式的直属上级时，默认审批人返回空数组，不回退 App owner。
  - 返回一个明确状态字段，例如 `approver_resolution_status`，用于前端展示。
- `src/easyauth/access_requests/submission_validation.py`
  - 保持最终审批人必须是 active EasyAuth 用户。
  - 对包含 `MANAGED_USERS` 的申请，如果 `approver_user_ids` 为空，返回明确错误。
- `src/easyauth/access_requests/services.py`
  - 审计里记录最终审批人，不需要单独记录审批人来源或重填原因。

前端改造：

- `frontend/src/pages/portal/hooks/useAccessRequestForm.ts`
  - 当选择目标包含 `MANAGED_USERS` 时，优先使用后端返回的直属上级默认审批人。
  - 用户手动修改审批人后，不再被自动回填覆盖。
- `frontend/src/pages/portal/components/AccessRequestFields.tsx`
  - 当后端返回直属上级缺失状态时展示：“未找到直属上级，请补全审批人”。
  - 审批人选择仍允许手动重填。

### 7. 试点数据、manifest 和文档

必须统一旧 `MANAGED` 命名：

- `src/easyauth/applications/management/commands/fixtures/crm_pilot_manifest.json`
- `src/easyauth/applications/management/commands/seed_crm_pilot.py`
- `tests/unit/applications/test_permission_templates_ops1.py`
- `tests/integration/admin/test_seed_crm_pilot.py`
- `docs/README.md`
- `CONTEXT.md`
- 仍包含旧 `MANAGED` 业务语义的 `docs/plans/*` 和 `docs/superpowers/plans/*`

要求：

- 新 manifest 声明 `MANAGED_USERS` scope。
- 使用管理范围的权限 `supported_scopes` 包含 `MANAGED_USERS`。
- 试点授权组 grant 使用 `MANAGED_USERS`。
- 不新增 `MANAGED` 到 `MANAGED_USERS` 的兼容转换。

## 实施阶段

### 阶段一：模型和契约安全网

- 新增 `ManagedScopePolicy` 模型、迁移和领域服务。
- 为有效策略计算写单元测试。
- 扩展公共权限查询 serializer 和领域类型，但先用测试锁定普通 grant 不受影响。
- 统一 `MANAGED_USERS` scope 的 fixture 和 manifest 测试。

建议并行：

- 子代理 A：模型、迁移、策略服务和测试。
- 子代理 B：公共查询 serializer、领域类型和 API 契约测试。
- 子代理 C：manifest、fixture、种子数据和相关测试。

### 阶段二：解析器和 Authentik 客户端

- 增加 Authentik managed users client 与 payload parser。
- 实现 `dingtalk_manager_chain` resolver。
- 接入 `resolve_user_permissions()`。
- 覆盖无策略、disabled、空下级、无绑定、stale、inactive、未绑定用户等分支。

建议并行：

- 子代理 A：Authentik client/parser/tests。
- 子代理 B：resolver service/tests。
- 子代理 C：公共权限查询集成测试。

### 阶段三：控制台配置、预览和健康检查

- 增加 App 默认策略 API。
- 扩展授权组 grant 保存 payload。
- 增加 managed users preview API。
- 扩展配置健康检查和 operations 输出。
- 前端 MatrixTab、QueryTestTab 和 App 默认策略入口同步改造。

建议并行：

- 子代理 A：控制台后端 API 与测试。
- 子代理 B：健康检查与预览服务。
- 子代理 C：前端控制台 UI 与 Vitest。

### 阶段四：员工门户申请

- 调整 request catalog 的默认审批人规则。
- 提交校验覆盖 `MANAGED_USERS` 审批人必填。
- 前端申请表显示直属上级缺失状态，并支持手动重填。

建议并行：

- 子代理 A：后端 portal/access_requests 流程与测试。
- 子代理 B：前端 portal 表单和测试。

### 阶段五：全量回归和运行态验证

- 运行后端单元与集成测试。
- 运行前端测试、typecheck 和 build。
- 运行 Django check、migration check、ruff、basedpyright。
- 修改 Django 后端、模板、React build 产物或 Vite manifest 后，必须重启当前 Django 开发服务，并用真实 HTTP 响应或浏览器页面确认新代码加载。

## 测试矩阵

后端重点测试：

- `tests/unit/grants/test_query.py`
- `tests/integration/api/test_permission_query.py`
- `tests/integration/api/test_permission_query_ops1.py`
- `tests/integration/authentik/test_directory_client.py`
- `tests/integration/admin_console/test_query_tester_ops1.py`
- `tests/integration/admin_console/test_dependency_health_ops3.py`
- `tests/integration/admin_console/test_apps_api_ops1.py`
- `tests/integration/portal/test_request_catalog_api.py`
- `tests/integration/portal/test_access_request_s14.py`
- `tests/unit/applications/test_permission_templates_ops1.py`
- `tests/integration/admin/test_seed_crm_pilot.py`

前端重点测试：

- `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`
- `frontend/src/pages/console/workspace/matrix/grantDraft.test.ts`
- `frontend/src/pages/portal/PortalPage.test.tsx`
- 必要时新增 `QueryTestTab` 或 `MatrixTab` 专项测试。

关键用例：

- 普通 scope grant 不带 `resolved`。
- `MANAGED_USERS` grant 带完整 resolved。
- App 默认策略生效。
- Grant 覆盖策略优先。
- 无有效策略时 grant 不生效。
- 策略有效但下级为空时保留 grant 且 `resolved.user_ids=[]`。
- 用户缺少 DingTalk 绑定时不返回管理范围 grant。
- 目录 stale 和无有效快照按设计阻断或诊断。
- inactive、deleted、未绑定 Authentik 用户不会进入 `resolved.user_ids`。
- 自助申请包含 `MANAGED_USERS` 时默认审批人为直属上级。
- 找不到直属上级时审批人留空，提交前必须补全。
- 用户手动重填审批人后不被自动覆盖。

## 验证命令

建议基础命令：

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/pytest tests/unit/grants tests/integration/api tests/integration/authentik -q
.venv/bin/pytest tests/integration/admin_console tests/integration/portal -q
.venv/bin/pytest tests/unit/applications/test_permission_templates_ops1.py tests/integration/admin/test_seed_crm_pilot.py -q
.venv/bin/ruff check src/easyauth tests
.venv/bin/basedpyright
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

涉及运行中页面响应的实现变更完成后，还必须：

```bash
DJANGO_DEBUG=1 EASYAUTH_ENABLE_DEV_LOGIN=1 .venv/bin/python manage.py runserver 127.0.0.1:8000
curl -i http://127.0.0.1:8000/console/
curl -i http://127.0.0.1:8000/portal/
```

公共权限查询真实响应需要使用有效 App 凭据验证：

```bash
curl -i \
  -H "Authorization: Bearer <app-token>" \
  http://127.0.0.1:8000/api/v1/apps/<app_key>/users/<authentik_user_id>/permissions
```

预期：

- 响应中 `MANAGED_USERS` grant 带 `resolved`。
- 普通 grant 不带 `resolved`。
- 页面 HTML 引用最新 Vite manifest 中的 asset。

## 风险与处理

- 策略模型过度简化会破坏继承和健康检查：必须使用独立 `ManagedScopePolicy`，不要只在 grant 上加一个字符串字段。
- 本地递归 DingTalk 下级容易引入多部门、循环链、未绑定用户和 stale 语义错误：第一版优先消费 Authentik 归一化接口。
- 公共查询链路被门户和联调页复用：所有变更必须先补测试，再实现。
- 员工门户当前有静态默认审批人逻辑：改造时要精确限定 `MANAGED_USERS` 场景，避免破坏普通授权申请体验。
- 旧 `MANAGED` 名称残留会导致上下游契约分裂：必须一次性改为 `MANAGED_USERS`，不保留兼容字段。

## 完成标准

- `MANAGED_USERS` scope、策略模型、解析服务、公共响应、控制台配置、预览、健康检查、自助申请规则全部落地。
- 所有旧 `MANAGED` 业务语义已迁移到 `MANAGED_USERS`。
- 后端与前端测试覆盖关键成功和失败分支。
- 前端 build 与 Django check 成功。
- 影响页面响应的变更已重启 Django 开发服务并用真实 HTTP 或浏览器验证。
