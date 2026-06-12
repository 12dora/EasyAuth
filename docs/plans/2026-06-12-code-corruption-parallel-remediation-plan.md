# EasyAuth 代码腐化并行修复实施计划

> **给代理执行者：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。任务使用复选框跟踪；每个任务完成前必须先补或运行对应回归测试。

**目标：** 将 2026-06-12 代码腐化扫描发现的超长组件/函数、重复业务口径、控制台 API 样板和测试保护缺口拆成可并行执行、可验证、可回滚的修复任务。

**架构：** 先补安全网，再收敛纯规则和重复 guard，随后拆前端组件与 Django 模板，最后处理模型规则和授权生命周期边界。所有阶段按写集隔离组织并行任务；公共 HTTP 路径、API 字段、Django URL name、React route 默认保持不变。

**技术栈：** Python 3.12、Django 5.2、Django REST Framework、pytest、ruff、basedpyright、React 19、TypeScript、Vite、Vitest、Playwright。

---

## 0. 扫描基线

本计划基于只读扫描结果制定，扫描排除了 `node_modules/`、缓存、构建产物、Django migrations、`src/easyauth/static/easyauth/frontend/` 等生成物。

- 源码扫描文件：304 个。
- 文件级违规：P0=0、P1=0、P2=0、P3=4。
- 符号级违规：P0=5、P1=11、P2=60、P3=4。
- import 循环：0。
- 主要风险：超长前端组件、控制台 API 重复 guard、状态/权限查询口径重复、核心行为缺少直接 characterization tests。

## 1. 全局执行规则

- 先测后改。每个任务先新增或运行能锁定当前行为的测试，再修改生产代码。
- 并行任务必须写集不重叠；同一阶段内共享文件只能由一个任务 owner 修改。
- 每个任务完成后运行任务级验证；每个阶段结束后运行阶段级门禁。
- 不新增依赖；不创建 migration；不改外部 API 契约，除非任务明确标记为行为修正。
- 文档正文使用中文；代码标识符、文件路径、命令、API 字段保留英文。
- 每个任务建议独立提交，提交信息用中文或中英混合均可，但必须说明业务边界。

## 2. 并行阶段总览

| 阶段 | 可并行泳道 | 主要目标 | 阶段门禁 |
|---|---|---|---|
| 阶段 0：安全网 | 0A 目标校验测试；0B 入站回调测试；0C portal 聚合测试；0D response helper 测试；0E 前端 e2e smoke | 只补测试，不改生产行为 | 目标测试均通过 |
| 阶段 1：重复口径收敛 | 1A 状态解析；1B 控制台 request guard；1C 权限查询认证/TTL；1D portal 状态文案 | 把重复业务规则收敛到单一模块 | 后端单元/集成目标测试通过 |
| 阶段 2：前端拆分 | 2A `AccessRequestForm`；2B `AppShell`；2C `CredentialsTab`；2D `MatrixTab`；2E 样式入口 | 拆超长组件和隐式样式顺序 | Vitest、typecheck、Playwright smoke 通过 |
| 阶段 3：后端结构拆分 | 3A `GrantService`；3B model 规则抽取；3C Django app detail 模板；3D admin API handler 瘦身 | 降低职责混杂和模板膨胀 | pytest admin/portal/grants/applications 通过 |
| 阶段 4：清理和门禁 | 4A 未用导出；4B 测试 fixture；4C 静态扫描脚本；4D 文档同步 | 删除低价值残留，固化质量门禁 | 全量 lint/typecheck/test/build 通过 |

建议并行度：阶段 0 可 5 个子代理；阶段 1 可 4 个子代理；阶段 2 可 5 个子代理；阶段 3 可 4 个子代理；阶段 4 可 4 个子代理。主代理负责合并、冲突处理和阶段门禁。

## 3. 共享文件锁

| 文件或目录 | 锁定规则 | 原因 |
|---|---|---|
| `frontend/src/lib/api.ts` | 阶段 2 只能由 2E 或主代理修改 | 前端 API helper 被多个组件依赖 |
| `frontend/src/lib/domain.ts` | 阶段 2 只能由主代理修改 | 类型定义共享，避免组件拆分冲突 |
| `frontend/src/main.tsx` | 阶段 2 只能由 2E 修改 | CSS import 顺序敏感 |
| `src/easyauth/admin_console/*_api.py` | 阶段 1B 与阶段 3D 不能并行修改同一文件 | request guard 与 handler 瘦身都触碰 API handler |
| `src/easyauth/applications/models.py` | 阶段 3B 独占 | Django model import 和 validation 敏感 |
| `src/easyauth/applications/ops_models.py` | 阶段 3B 独占 | Django model import 和 validation 敏感 |
| `src/easyauth/grants/services.py` | 阶段 3A 独占 | 授权生命周期核心边界 |
| `src/easyauth/admin_console/templates/admin_console/app_detail.html` | 阶段 3C 独占 | 模板上下文和 include 顺序敏感 |

## 4. 阶段 0：安全网

### 任务 0A：补申请目标校验直接单测

**建议子代理：** `test-engineer`

**文件：**
- 新建：`tests/unit/access_requests/test_target_validation.py`
- 阅读：`src/easyauth/access_requests/target_validation.py:21`
- 阅读：`src/easyauth/access_requests/application_target_validation.py`
- 阅读：`src/easyauth/access_requests/submission_validation.py`

- [ ] **步骤 1：新增 direct validator 测试文件。**
  覆盖 `role_target_errors`、`permission_target_errors`、`validate_request_targets`。

- [ ] **步骤 2：覆盖 role 规则。**
  构造跨 App role、inactive role、`requestable=False` role，断言错误消息包含当前英文消息并保持聚合顺序。

- [ ] **步骤 3：覆盖 permission 规则。**
  构造跨 App permission、inactive permission、deprecated permission、没有 active approval rule 的 direct permission，断言错误消息稳定。

- [ ] **步骤 4：覆盖多错误同时返回。**
  同一次调用传入多个非法 role/permission，断言返回 tuple 顺序与当前实现一致。

- [ ] **步骤 5：运行测试。**

```bash
pytest tests/unit/access_requests/test_target_validation.py \
  tests/unit/access_requests/test_services_s14_validation.py \
  tests/unit/access_requests/test_services_ops4_application_target_stale.py -q
```

预期：全部通过。

### 任务 0B：补入站审批回调服务单测

**建议子代理：** `test-engineer`

**文件：**
- 新建：`tests/unit/access_requests/test_inbound_callbacks.py`
- 阅读：`src/easyauth/access_requests/inbound_callbacks.py:44`
- 阅读：`src/easyauth/integrations/dingtalk/callbacks.py`
- 阅读：`tests/integration/integrations/test_dingtalk_callback.py`

- [ ] **步骤 1：新增 `apply_approval_callback` submitted -> rejected 测试。**
  断言申请状态、审计事件、授权事实都符合当前行为。

- [ ] **步骤 2：新增 unknown process 测试。**
  断言返回 kind 为当前实现的 security/validation 分类，并写入审计证据。

- [ ] **步骤 3：新增 approved 遇到 `AccessRequestApplicationError` 测试。**
  mock 或构造应用授权失败路径，断言 kind 为 `application_error`。

- [ ] **步骤 4：新增非法 status 测试。**
  断言 kind 为 `validation_error`，且申请和授权不变。

- [ ] **步骤 5：运行测试。**

```bash
pytest tests/unit/access_requests/test_inbound_callbacks.py \
  tests/integration/integrations/test_dingtalk_callback.py -q
```

预期：全部通过。

### 任务 0C：补 portal 权限聚合单测

**建议子代理：** `test-engineer`

**文件：**
- 新建：`tests/unit/portal/test_permission_aggregation.py`
- 阅读：`src/easyauth/portal/permission_aggregation.py`
- 阅读：`src/easyauth/portal/api_data.py`
- 阅读：`src/easyauth/portal/grant_rows.py`

- [ ] **步骤 1：覆盖空 grant id。**
  调用 `direct_permission_keys_by_grant_id`，断言为每个输入 grant id 预填空 set。

- [ ] **步骤 2：覆盖 `active_only=True`。**
  构造 inactive/deprecated permission，断言当前权限 API 不返回它们。

- [ ] **步骤 3：覆盖 `active_only=False`。**
  构造历史授权展示场景，断言保留历史权限用于 row 展示。

- [ ] **步骤 4：覆盖去重和排序。**
  role permission 与 direct permission 重复时只返回一次，且按 permission key 排序。

- [ ] **步骤 5：运行测试。**

```bash
pytest tests/unit/portal/test_permission_aggregation.py \
  tests/integration/portal/test_my_permissions_ops2.py \
  tests/integration/portal/test_portal_api_ops4_permissions.py -q
```

预期：全部通过。

### 任务 0D：补 response helper 契约单测

**建议子代理：** `test-engineer`

**文件：**
- 新建或修改：`tests/unit/api/test_responses.py`
- 阅读：`src/easyauth/api/responses.py:10`
- 阅读：`src/easyauth/api/errors.py:33`
- 阅读：`src/easyauth/admin_console/api_responses.py`

- [ ] **步骤 1：覆盖 `json_response` 中文不转义。**
  断言响应内容可解析且原始 bytes 不包含中文转义序列。

- [ ] **步骤 2：覆盖 `error_response` details 默认值。**
  `details=None` 时输出 `{}`，HTTP status 支持 `HTTPStatus` 和 int。

- [ ] **步骤 3：覆盖 admin console re-export。**
  从 `easyauth.admin_console.api_responses` 导入的函数与公共 helper 行为一致。

- [ ] **步骤 4：运行测试。**

```bash
pytest tests/unit/api/test_responses.py tests/integration/api/test_contract.py -q
```

预期：全部通过。

### 任务 0E：补前端布局 smoke

**建议子代理：** `test-engineer`

**文件：**
- 修改：`frontend/e2e/smoke.spec.ts`
- 阅读：`frontend/playwright.config.ts`
- 阅读：`frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 阅读：`frontend/src/pages/console/ConsoleAppWorkspace.tsx`

- [ ] **步骤 1：新增 portal request smoke。**
  访问 `/portal/request`，断言申请表关键控件可见。

- [ ] **步骤 2：新增 console credentials smoke。**
  访问 `/console/apps/demo?tab=credentials`，断言凭据 tab 关键控件可见。

- [ ] **步骤 3：新增 console matrix smoke。**
  访问 `/console/apps/demo?tab=matrix`，断言矩阵区域关键控件可见。

- [ ] **步骤 4：覆盖 desktop 和 mobile viewport。**
  至少使用 1280x800 与 390x844 两档；断言关键按钮没有被遮挡。

- [ ] **步骤 5：运行 e2e。**

```bash
pnpm --dir frontend e2e
```

预期：全部通过。

## 5. 阶段 1：重复口径收敛

### 任务 1A：统一状态解析规则

**建议子代理：** `executor`

**文件：**
- 新建：`src/easyauth/accounts/status.py`
- 新建：`src/easyauth/grants/status.py`
- 修改：`src/easyauth/accounts/services.py:87`
- 修改：`src/easyauth/grants/operations.py:29`
- 修改：`src/easyauth/grants/query.py:117`
- 测试：`tests/unit/accounts/test_status.py`
- 测试：`tests/unit/grants/test_status.py`

- [ ] **步骤 1：为现有解析行为写测试。**
  覆盖 `active/disabled/departed` 用户状态和 `active/revoked/expired` 授权状态；非法值必须抛当前异常类型或保持当前错误语义。

- [ ] **步骤 2：新增 `accounts/status.py`。**
  提供 `parse_user_status(status: str)`、`is_non_active_status(status: str)`，用现有常量作为唯一枚举来源。

- [ ] **步骤 3：新增 `grants/status.py`。**
  提供 `parse_grant_status(status: str)`，替换 `operations.py` 与 `query.py` 的本地解析。

- [ ] **步骤 4：删除重复私有函数。**
  删除 `_parse_user_status`、`_parse_grant_status`、`_is_non_active_status` 的重复实现，保留 public API 不变。

- [ ] **步骤 5：运行测试。**

```bash
pytest tests/unit/accounts tests/unit/grants tests/integration/api/test_permission_query.py -q
ruff check src/easyauth/accounts src/easyauth/grants tests/unit/accounts tests/unit/grants
```

预期：全部通过。

### 任务 1B：统一控制台 request guard

**建议子代理：** `executor`

**文件：**
- 新建：`src/easyauth/admin_console/request_guards.py`
- 新建或修改：`tests/unit/admin_console/test_request_guards.py`
- 修改：`src/easyauth/admin_console/approval_rules_api.py`
- 修改：`src/easyauth/admin_console/permission_template_api.py`
- 修改：`src/easyauth/admin_console/permission_catalog_api.py`
- 修改：`src/easyauth/admin_console/audit_api.py`
- 修改：`src/easyauth/admin_console/query_test_api.py`
- 修改：`src/easyauth/admin_console/apps_api.py`
- 修改：`src/easyauth/admin_console/credentials_api.py`
- 修改：`src/easyauth/admin_console/memberships_api.py`
- 修改：`src/easyauth/admin_console/console_app_api.py`

- [ ] **步骤 1：测试当前 actor guard 契约。**
  覆盖未登录返回 401、已登录映射为 `ConsoleActor`、`request.user.is_superuser` 传递正确。

- [ ] **步骤 2：新增 `require_console_actor(request)`。**
  返回 `ConsoleActor | JsonResponse`，错误响应沿用 `ErrorCode.AUTHENTICATION_FAILED` 和当前中文消息。

- [ ] **步骤 3：新增 `require_post(request)`。**
  非 POST 返回 405，错误码和消息保持当前 `请求方法无效。`。

- [ ] **步骤 4：逐文件替换 `_actor_from_request` 和 method guard。**
  每次替换 1-2 个文件并运行对应集成测试；避免一次性大改。

- [ ] **步骤 5：运行测试。**

```bash
pytest tests/unit/admin_console/test_request_guards.py tests/integration/admin_console -q
ruff check src/easyauth/admin_console tests/unit/admin_console tests/integration/admin_console
```

预期：全部通过。

### 任务 1C：统一权限查询认证和 TTL

**建议子代理：** `executor`

**文件：**
- 新建：`src/easyauth/api/permission_query_auth.py`
- 修改：`src/easyauth/api/views.py:67`
- 修改：`src/easyauth/admin_console/query_tester.py:145`
- 测试：`tests/integration/api/test_authentication.py`
- 测试：`tests/integration/admin_console/test_query_tester_ops1.py`

- [ ] **步骤 1：补正式 API 与联调 API 差异测试。**
  覆盖 token disabled、app disabled、TTL 配置非法值、TTL 未配置默认值。

- [ ] **步骤 2：新增 `permission_query_auth.py`。**
  提供 `authenticate_permission_query_token(token: str)` 与 `permission_query_ttl_seconds()`。

- [ ] **步骤 3：替换正式 API。**
  `api/views.py` 只负责 HTTP request/response 编排，不再本地解析 TTL。

- [ ] **步骤 4：替换联调 API。**
  `query_tester.py` 复用同一认证和 TTL helper，同时保留联调专属 result envelope。

- [ ] **步骤 5：运行测试。**

```bash
pytest tests/integration/api/test_authentication.py \
  tests/integration/api/test_permission_query.py \
  tests/integration/admin_console/test_query_tester_ops1.py -q
```

预期：全部通过。

### 任务 1D：统一 portal 状态文案

**建议子代理：** `executor`

**文件：**
- 新建：`src/easyauth/portal/status_text.py`
- 修改：`src/easyauth/portal/views.py:182`
- 修改：`src/easyauth/portal/access_request_data.py:117`
- 测试：`tests/unit/portal/test_status_text.py`
- 测试：`tests/integration/portal/test_portal_api_ops2.py`

- [ ] **步骤 1：测试现有状态文案。**
  覆盖 `submitted`、`approved`、`grant_applied`、`rejected`、`grant_failed` 和未知状态。

- [ ] **步骤 2：新增 `status_text.py`。**
  提供 `status_label(status: str)` 与 `status_tone(status: str)`，把中文文案和 tone 放在同一权威来源。

- [ ] **步骤 3：替换两个调用方。**
  `portal/views.py` 和 `portal/access_request_data.py` 不再维护本地 mapping。

- [ ] **步骤 4：运行测试。**

```bash
pytest tests/unit/portal/test_status_text.py tests/integration/portal/test_portal_api_ops2.py -q
```

预期：全部通过。

## 6. 阶段 2：前端拆分

### 任务 2A：拆 `AccessRequestForm`

**建议子代理：** `executor`

**文件：**
- 修改：`frontend/src/pages/portal/components/AccessRequestForm.tsx:15`
- 新建：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts`
- 新建：`frontend/src/pages/portal/components/AccessRequestFields.tsx`
- 新建：`frontend/src/pages/portal/components/RequestTargetPicker.tsx`
- 测试：`frontend/src/pages/portal/PortalPage.test.tsx`

- [ ] **步骤 1：运行现有前端测试。**

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx src/pages/portal/permissionTree.test.ts
```

- [ ] **步骤 2：抽 `useAccessRequestForm`。**
  移出表单状态、提交状态、toast 状态、提交处理；hook 返回字段值、事件 handler、提交状态和 toast 数据。

- [ ] **步骤 3：抽 `AccessRequestFields`。**
  承担申请类型、理由、时长等普通字段渲染，不触碰 API。

- [ ] **步骤 4：抽 `RequestTargetPicker`。**
  承担 role/permission 选择器组合，复用已有 `PermissionSelector` 与 `permissionTree.ts`。

- [ ] **步骤 5：收缩原组件。**
  `AccessRequestForm.tsx` 只组合 hook 和子组件，目标小于 60 SLOC。

- [ ] **步骤 6：运行验证。**

```bash
pnpm --dir frontend test -- --run src/pages/portal
pnpm --dir frontend typecheck
```

预期：全部通过。

### 任务 2B：拆 `AppShell`

**建议子代理：** `executor`

**文件：**
- 修改：`frontend/src/components/AppShell.tsx:15`
- 新建：`frontend/src/components/shell/Topbar.tsx`
- 新建：`frontend/src/components/shell/Sidebar.tsx`
- 新建：`frontend/src/components/shell/ShellNav.tsx`
- 新建：`frontend/src/components/shell/UserSummary.tsx`

- [ ] **步骤 1：运行前端类型检查。**

```bash
pnpm --dir frontend typecheck
```

- [ ] **步骤 2：抽 `Topbar`。**
  移出品牌、用户摘要和顶栏动作。

- [ ] **步骤 3：抽 `Sidebar` 和 `ShellNav`。**
  移出导航分组、active 状态、active indicator 渲染。

- [ ] **步骤 4：保留 public props。**
  `AppShellProps` 对外保持 `brandLogoUrl`、`currentUserId`、`mode` 不变。

- [ ] **步骤 5：运行验证。**

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
```

预期：全部通过。

### 任务 2C：拆 `CredentialsTab`

**建议子代理：** `executor`

**文件：**
- 修改：`frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx:17`
- 新建：`frontend/src/pages/console/workspace/credentials/CredentialTable.tsx`
- 新建：`frontend/src/pages/console/workspace/credentials/CreateCredentialForm.tsx`
- 新建：`frontend/src/pages/console/workspace/credentials/useCredentialsActions.ts`
- 测试：`frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`

- [ ] **步骤 1：运行现有工作台测试。**

```bash
pnpm --dir frontend test -- --run src/pages/console/ConsoleAppWorkspace.test.tsx
```

- [ ] **步骤 2：抽 `useCredentialsActions`。**
  移出 create、rotate、disable、secret dialog 状态和 API 调用。

- [ ] **步骤 3：抽 `CredentialTable`。**
  只负责展示 credentials 和触发 handler。

- [ ] **步骤 4：抽 `CreateCredentialForm`。**
  只负责创建 static token / OAuth client 的输入和提交。

- [ ] **步骤 5：运行验证。**

```bash
pnpm --dir frontend test -- --run src/pages/console/ConsoleAppWorkspace.test.tsx
pnpm --dir frontend typecheck
```

预期：全部通过。

### 任务 2D：拆 `MatrixTab`

**建议子代理：** `executor`

**文件：**
- 修改：`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx:11`
- 新建：`frontend/src/pages/console/workspace/matrix/RolePermissionMatrix.tsx`
- 新建：`frontend/src/pages/console/workspace/matrix/useMatrixDraft.ts`
- 测试：`frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`

- [ ] **步骤 1：补或运行 matrix 交互测试。**
  断言勾选权限后 PATCH body 包含 `base_version` 和变更 assignments。

- [ ] **步骤 2：抽 `useMatrixDraft`。**
  负责 draft 状态、diff 计算、保存 payload 构造。

- [ ] **步骤 3：抽 `RolePermissionMatrix`。**
  负责表格渲染和 checkbox 事件。

- [ ] **步骤 4：收缩 `MatrixTab`。**
  只负责 query/mutation 和子组件组合，目标小于 50 SLOC。

- [ ] **步骤 5：运行验证。**

```bash
pnpm --dir frontend test -- --run src/pages/console/ConsoleAppWorkspace.test.tsx
pnpm --dir frontend typecheck
```

预期：全部通过。

### 任务 2E：整理样式入口

**建议子代理：** `executor`

**文件：**
- 新建：`frontend/src/styles/index.css`
- 修改：`frontend/src/main.tsx`
- 阅读：`frontend/src/styles/layout-shell.css`
- 阅读：`frontend/src/styles/components/*.css`
- 阅读：`frontend/src/styles/features/*.css`

- [ ] **步骤 1：记录当前 import 顺序。**
  从 `main.tsx` 复制现有样式 import 顺序，作为 `index.css` 的 `@import` 顺序。

- [ ] **步骤 2：新增 `styles/index.css`。**
  用 `@import` 聚合 tokens、layout、components、features、responsive。

- [ ] **步骤 3：更新 `main.tsx`。**
  删除多条 CSS import，仅保留 `import "./styles/index.css";`。

- [ ] **步骤 4：运行验证。**

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend build
pnpm --dir frontend e2e
```

预期：全部通过；视觉 smoke 不回归。

## 7. 阶段 3：后端结构拆分

### 任务 3A：拆 `GrantService`

**建议子代理：** `executor`

**文件：**
- 修改：`src/easyauth/grants/services.py:81`
- 新建：`src/easyauth/grants/lifecycle.py`
- 新建：`src/easyauth/grants/expiration.py`
- 测试：`tests/unit/grants/test_services.py`
- 测试：`tests/unit/grants/test_expiration_cleanup_s13.py`

- [ ] **步骤 1：运行 grants 当前测试。**

```bash
pytest tests/unit/grants tests/integration/api/test_grant_lifecycle_s13.py -q
```

- [ ] **步骤 2：抽 expiration。**
  将到期清理和 expire grant 相关纯逻辑移到 `expiration.py`，`GrantService.expire_grant` 保留兼容调用。

- [ ] **步骤 3：抽 lifecycle operation。**
  将 revoke/renew/activate 的条件判断移到 `lifecycle.py`，`GrantService` 只做事务编排。

- [ ] **步骤 4：收缩 `GrantService`。**
  类目标小于 100 SLOC，单方法目标小于 40 SLOC。

- [ ] **步骤 5：运行验证。**

```bash
pytest tests/unit/grants tests/integration/api/test_grant_lifecycle_s13.py -q
ruff check src/easyauth/grants tests/unit/grants
```

预期：全部通过。

### 任务 3B：抽 Django model 规则

**建议子代理：** `executor`

**文件：**
- 修改：`src/easyauth/applications/models.py:228`
- 修改：`src/easyauth/applications/ops_models.py:131`
- 新建：`src/easyauth/applications/approval_rule_rules.py`
- 新建：`src/easyauth/applications/permission_group_rules.py`
- 新建：`src/easyauth/applications/role_access_policy_rules.py`
- 测试：`tests/unit/applications/test_models.py`

- [ ] **步骤 1：补 model clean characterization tests。**
  覆盖 ApprovalRule 单 target、跨 App、approver_userids；PermissionGroup parent 跨 App、cycle、depth；RoleAccessPolicy high-risk shape。

- [ ] **步骤 2：抽 `approval_rule_rules.py`。**
  提供 `approval_rule_clean_errors(rule) -> dict[str, str]`，model `clean()` 只负责调用并抛 `ValidationError`。

- [ ] **步骤 3：抽 `permission_group_rules.py`。**
  提供 depth/cycle 校验函数，保持原错误消息。

- [ ] **步骤 4：抽 `role_access_policy_rules.py`。**
  提供 max duration shape 校验函数，保持原错误消息。

- [ ] **步骤 5：运行验证。**

```bash
pytest tests/unit/applications/test_models.py tests/unit/applications -q
python manage.py check
basedpyright
```

预期：全部通过；不生成 migration。

### 任务 3C：拆 Django app detail 模板

**建议子代理：** `executor`

**文件：**
- 修改：`src/easyauth/admin_console/templates/admin_console/app_detail.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_readiness.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_permission_template.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_role_permission_matrix.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_query_tester.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_integration_guide.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_roles_permissions.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_credentials.html`
- 新建：`src/easyauth/admin_console/templates/admin_console/app_detail/_approval_rules.html`
- 测试：`tests/integration/admin_console/test_app_detail_ops1.py`

- [ ] **步骤 1：运行当前 app detail 测试。**

```bash
pytest tests/integration/admin_console/test_app_detail_ops1.py -q
```

- [ ] **步骤 2：先抽纯展示 partial。**
  抽 29-45、184-213、217-292 的展示区块，父模板用 `{% include %}`。

- [ ] **步骤 3：再抽包含表单的 partial。**
  抽 47-103、105-147、149-182、294-386，确保 `{% csrf_token %}` 仍在对应 form 内。

- [ ] **步骤 4：补测试断言。**
  在 `test_app_detail_ops1.py` 断言每个区块关键文本和 form action 仍存在。

- [ ] **步骤 5：运行验证。**

```bash
pytest tests/integration/admin_console/test_app_detail_ops1.py -q
python manage.py check
```

预期：全部通过；父模板目标小于 120 SLOC。

### 任务 3D：瘦身 admin API handler

**建议子代理：** `executor`

**文件：**
- 修改：`src/easyauth/admin_console/operations_api.py:80`
- 修改：`src/easyauth/admin_console/permission_catalog_api.py:101`
- 修改：`src/easyauth/admin_console/permission_template_api.py:59`
- 修改：`src/easyauth/admin_console/approval_rules_api.py:123`
- 新建：`src/easyauth/admin_console/permission_catalog_handlers.py`
- 新建：`src/easyauth/admin_console/permission_template_handlers.py`
- 新建：`src/easyauth/admin_console/approval_rule_handlers.py`

- [ ] **步骤 1：逐文件运行现有集成测试。**

```bash
pytest tests/integration/admin_console/test_permission_catalog_api_ops1.py \
  tests/integration/admin_console/test_permission_catalog_write_api_ops1.py \
  tests/integration/admin_console/test_template_guide_api_ops1.py \
  tests/integration/admin_console/test_approval_rules_api_ops1.py \
  tests/integration/admin_console/test_operations_api_ops3.py -q
```

- [ ] **步骤 2：抽 catalog mutation handler。**
  `_save_matrix` 和 `_matrix_mutations` 只保留 HTTP glue，业务 mutation 移到 `permission_catalog_handlers.py`。

- [ ] **步骤 3：抽 permission template handler。**
  preview/confirm 的解析、导入、错误映射移到 `permission_template_handlers.py`。

- [ ] **步骤 4：抽 approval rule patch handler。**
  `_patch_rule` 的 payload 到 model 更新逻辑移到 `approval_rule_handlers.py`。

- [ ] **步骤 5：运行验证。**

```bash
pytest tests/integration/admin_console -q
ruff check src/easyauth/admin_console tests/integration/admin_console
```

预期：全部通过；被拆 handler 单函数小于 40 SLOC。

## 8. 阶段 4：清理和门禁

### 任务 4A：清理前端未用导出

**建议子代理：** `executor`

**文件：**
- 修改或删除：`frontend/src/lib/api.ts:12`
- 修改或删除：`frontend/src/components/ConfirmDialog.tsx:14`

- [ ] **步骤 1：确认无引用。**

```bash
rg -n "PaginatedPayload|ConfirmDialog" frontend/src
```

- [ ] **步骤 2：删除无用导出或补齐真实引用。**
  如果仍只有定义，删除 `PaginatedPayload` 和 `ConfirmDialog`；如果产品需要确认弹窗，改为在真实禁用/删除动作处接入并补测试。

- [ ] **步骤 3：运行验证。**

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
```

预期：全部通过。

### 任务 4B：抽测试 fixture helper

**建议子代理：** `executor`

**文件：**
- 新建：`tests/integration/portal/helpers.py`
- 修改：`tests/integration/portal/test_my_permissions_ops2.py`
- 修改：`tests/integration/portal/test_portal_api_ops4.py`
- 修改：`tests/integration/portal/test_access_request_s14.py`
- 修改：`tests/integration/portal/test_request_catalog_api.py`
- 修改：`tests/integration/portal/test_portal_api_ops4_permissions.py`
- 修改：`tests/integration/portal/test_portal_api_pagination.py`

- [ ] **步骤 1：新增 `logged_in_client(authentik_user_id)` helper。**
  迁移重复 `_logged_in_client` 实现，保持返回 `tuple[Client, UserMirror]`。

- [ ] **步骤 2：逐文件替换重复 helper。**
  每次替换 1-2 个测试文件。

- [ ] **步骤 3：运行验证。**

```bash
pytest tests/integration/portal -q
ruff check tests/integration/portal
```

预期：全部通过。

### 任务 4C：新增腐化扫描脚本

**建议子代理：** `executor`

**文件：**
- 新建：`scripts/code_health_scan.py`
- 修改：`docs/README.md` 或 `docs/plans/2026-06-12-code-corruption-parallel-remediation-plan.md`

- [ ] **步骤 1：新增只读扫描脚本。**
  统计 Raw LOC、SLOC、函数长度、class 长度、fan-in/fan-out、重复 8 行片段，默认排除生成物和 migrations。

- [ ] **步骤 2：输出 JSON 和 Markdown 摘要。**
  默认写到 stdout，不写仓库文件，除非传入 `--output`。

- [ ] **步骤 3：记录命令。**

```bash
python3 scripts/code_health_scan.py --root .
```

该命令默认向 stdout 输出 JSON，结果中包含 `markdown_summary` 摘要；如需直接查看 Markdown 摘要，可追加 `--format markdown`。脚本默认只读，不写仓库文件；只有显式传入 `--output` 时才会把所选格式写入指定路径。

- [ ] **步骤 4：运行验证。**

```bash
python3 scripts/code_health_scan.py --root . >/tmp/easyauth-code-health.json
python3 -m py_compile scripts/code_health_scan.py
```

预期：脚本只读执行成功。

### 任务 4D：全量质量门禁

**建议子代理：** `verifier`

**文件：**
- 不改生产文件；只记录验证结果。

- [ ] **步骤 1：运行 Python 静态检查。**

```bash
ruff check src tests
basedpyright
```

- [ ] **步骤 2：运行 Python 测试。**

```bash
pytest -q
```

- [ ] **步骤 3：运行前端检查。**

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
pnpm --dir frontend build
pnpm --dir frontend e2e
```

- [ ] **步骤 4：运行 Django check。**

```bash
python manage.py check
```

- [ ] **步骤 5：更新计划状态。**
  在本计划底部记录最终通过的命令、失败项和剩余风险；不要把命令输出全文粘贴进文档，只记录高信号摘要。

## 9. 推荐子代理派发顺序

阶段 0 可一次派发 5 个只测任务，全部完成后主代理合并测试；任何测试失败先修测试 fixture，不改生产代码。

阶段 1 推荐派发 1A、1C、1D 并行；1B 单独派发，因为它会触碰多个 `admin_console/*_api.py`。1B 完成后再运行 `pytest tests/integration/admin_console -q`。

阶段 2 推荐派发 2A、2B、2C、2D 并行；2E 单独由主代理执行或最后执行，因为它触碰 `main.tsx` 和 CSS 全局顺序。

阶段 3 推荐先执行 3A 和 3B 并行；3C 和 3D 可并行，但 3D 必须等 1B 完成。阶段 3 每合并一个任务都运行对应集成测试，避免后端边界漂移。

阶段 4 推荐 4A、4B、4C 并行；4D 必须最后执行。

## 10. 第一周执行排期

| Day | 目标 | 并行任务 | 验证 |
|---:|---|---|---|
| 1 | 补安全网 | 0A、0B、0C、0D、0E | 目标 pytest/Vitest/Playwright |
| 2 | 收敛纯规则 | 1A、1C、1D | `pytest tests/unit tests/integration/api tests/integration/portal -q` |
| 3 | 收敛控制台 guard | 1B | `pytest tests/integration/admin_console -q` |
| 4 | 拆前端组件 | 2A、2B、2C、2D | `pnpm --dir frontend test -- --run && pnpm --dir frontend typecheck` |
| 5 | 样式入口与后端 service | 2E、3A | frontend build/e2e、grants tests |
| 6 | 模型规则与模板拆分 | 3B、3C | applications tests、app detail tests、`python manage.py check` |
| 7 | admin handler 瘦身与清理 | 3D、4A、4B、4C、4D | 全量质量门禁 |

## 11. 回滚策略

- 每个任务独立提交；阶段失败时优先回滚该任务提交，不回滚其他已验证任务。
- 纯抽取任务必须保留原 public import 或原组件 props；回滚时只需把调用方 import 指回旧文件。
- 模板拆分回滚方式：恢复父模板内联区块，删除 partial include。
- 前端样式入口回滚方式：恢复 `main.tsx` 多文件 import，删除 `styles/index.css`。
- 后端 guard 抽取回滚方式：恢复单个 API 文件本地 `_actor_from_request`，不要批量回滚整个阶段。

## 12. 完成定义

- 所有 P0/P1 符号降级到 P2 或以下，普通函数目标小于 40 SLOC，组件目标小于 80 SLOC。
- 控制台 API actor/method/app guard 只有一个权威实现。
- 权限查询正式 API 和联调 API 共享认证/TTL 口径。
- portal 状态文案只有一个权威 mapping。
- 文件级 P3 中至少完成 `app_detail.html` 和 `layout-shell.css` 的拆分或入口收敛。
- 全量 `ruff check src tests`、`basedpyright`、`pytest -q`、`pnpm --dir frontend typecheck`、`pnpm --dir frontend test -- --run`、`pnpm --dir frontend build`、`pnpm --dir frontend e2e`、`python manage.py check` 通过；如某项因环境不可用不能运行，必须在最终报告中说明原因和替代验证。

## 13. 最终验证摘要（2026-06-12）

阶段 0 到阶段 4 已按本计划执行完毕，最终质量门禁均在当前 worktree 通过。

- `ruff check src tests`：通过。
- `basedpyright`：通过，`0 errors, 0 warnings, 0 notes`。
- `pytest -q`：通过，`526 passed`。
- `pnpm --dir frontend typecheck`：通过。
- `pnpm --dir frontend test -- --run`：通过，`8 files / 23 tests`。
- `pnpm --dir frontend build`：通过。
- `pnpm --dir frontend e2e`：通过，`8 passed`。
- `python manage.py check`（本地以 `.venv/bin/python manage.py check` 执行）：通过，`0 issues`。
- `python3 scripts/code_health_scan.py --root .`：通过，扫描 350 个文件；未发现非测试普通生产函数超过 40 SLOC。剩余非测试超 40 SLOC 项为 `frontend/src/pages/console/ConsoleAppList.tsx` 的 `ConsoleAppList` 组件，70 SLOC，低于组件 80 SLOC 目标。

剩余风险：`scripts/code_health_scan.py` 的 fan-in/fan-out 与 TypeScript/JavaScript 函数识别使用标准库启发式扫描，不等同于完整语言服务器分析；用于本计划 4C/4D 的只读质量门禁足够，但不替代后续架构评审。
