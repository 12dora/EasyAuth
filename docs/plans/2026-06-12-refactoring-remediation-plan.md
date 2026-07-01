# EasyAuth 重构修复实施计划

> **给代理执行者：** 实施本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`。任务使用复选框跟踪；每个任务完成前必须先补或运行对应回归测试。

**目标：** 将代码腐化扫描中发现的 P0/P2 文件膨胀、重复规则、边界耦合和测试缺口拆成可并行执行、可验证、可回滚的修复任务。

**架构：** 先补安全网，再拆无副作用前端样式和纯函数，随后拆页面组件与后端重复辅助函数，最后处理跨层边界。所有外部 HTTP 路径、公开 API 字段、Django URL name、React route 保持不变；项目尚未生产，不新增长期兼容层。

**技术栈：** Python 3.12、Django 5.2、Django REST Framework、pytest、ruff、basedpyright、React 19、TypeScript、Vite、Vitest、Playwright。

---

## 0. 执行规则

- 本计划从扫描报告中落地，覆盖 `frontend/src/styles.css`、`frontend/src/pages/portal/PortalPage.tsx`、`frontend/src/pages/console/ConsoleAppWorkspace.tsx`、`src/easyauth/portal/api.py`、`src/easyauth/access_requests/submission_validation.py`、`src/easyauth/admin_console/*_api.py`、`src/easyauth/integrations/dingtalk/callbacks.py`、`src/easyauth/accounts/oidc_exchange.py`、`src/easyauth/api/authentication.py`。
- 先测后改。每个任务的第一步是新增或运行能锁定当前行为的测试。
- 并行任务必须写集互不重叠；同一文件只能由一个执行者在同一阶段修改。
- 每个任务完成后运行本任务命令；每个阶段结束后运行阶段质量门禁。
- 不新增依赖；不改数据库 schema；不改外部 URL、API 字段、错误码语义，除非任务明确要求修正错误模型。
- 文档和提交说明使用中文；代码标识符、路径、命令、API 字段保留英文。

## 1. 阶段总览与并行矩阵

| 阶段 | 可并行泳道 | 主要目标 | 进入下一阶段条件 |
|---|---|---|---|
| 阶段 0：安全网 | A 前端工作台测试；B OIDC/认证测试；C 凭据 API 测试；D DingTalk 回调测试 | 锁定高风险行为，不改生产代码 | 新增测试能失败或能证明当前行为；相关测试通过 |
| 阶段 1：低风险拆分 | A CSS 拆分；B Portal 纯函数拆分；C 后端通用辅助函数抽取 | 移除无副作用膨胀和重复辅助函数 | 类型检查、静态检查、目标测试通过 |
| 阶段 2：组件/API 拆分 | A Portal 页面拆分；B Console 工作台拆分；C portal API catalog 拆分；D query tester 拆分 | 拆 P2 页面和超长函数 | 每条泳道独立测试通过，全量前后端冒烟 通过 |
| 阶段 3：边界修复 | A access request 目标校验统一；B portal 权限聚合统一；C DingTalk inbound service；D applications 包导入修复 | 收敛重复业务规则和跨层依赖 | 后端单测/集成测试、类型检查、Django check 通过 |

建议并行度：阶段 0 可 4 个子代理；阶段 1 可 3 个子代理；阶段 2 可 4 个子代理；阶段 3 可 4 个子代理。主代理负责合并、冲突处理和阶段门禁。

### 冻结点与集成 owner

| 冻结点 | 冻结内容 | 单一集成负责人 | 说明 |
|---|---|---|---|
| F0 | 高风险行为测试语义 | 主代理 | 阶段 0 结束后，测试期望必须先评审再改动 |
| F1 | 前端 route、公共 API 字段、错误响应结构 | 主代理 | 阶段 1 结束后，拆文件不得顺手改契约 |
| F2 | 控制台 tab/API 形状与 portal API payload | `console-frontend-agent`、`portal-api-agent` 分别集成，主代理最终合并 | 阶段 2 并行时禁止多个代理同时改 `frontend/src/lib/domain.ts` 或 `frontend/src/lib/api.ts` |
| F3 | 领域边界与入站回调职责 | 主代理 | 阶段 3 涉及跨层移动，必须一次只合并一个领域任务 |

### 高冲突文件清单

- 控制台总入口：`src/easyauth/admin_console/views.py`、`src/easyauth/admin_console/urls.py`、`src/easyauth/admin_console/view_data.py`、`src/easyauth/admin_console/templates/admin_console/app_detail.html`。同一阶段只允许一个 owner 修改。
- 领域事务边界：`src/easyauth/applications/services.py`、`src/easyauth/applications/models.py`、`src/easyauth/grants/services.py`、`src/easyauth/access_requests/services.py`。阶段 3 前禁止顺手改这些文件。
- 门户前后端交界：`src/easyauth/portal/views.py`、`src/easyauth/portal/forms.py`、`frontend/src/pages/portal/PortalPage.tsx`、`frontend/src/App.tsx`。前端拆分不能改变后端 legacy 行为。
- 路由与契约：`src/easyauth/config/urls.py`、`src/easyauth/api/urls.py`、`frontend/src/lib/domain.ts`、`frontend/src/lib/api.ts`。如需修改，只能由阶段 owner 统一提交。
- 迁移目录：`src/easyauth/*/migrations/`。本计划不创建 migration；如果验证发现 migration drift，先停止并单独开迁移任务。

## 2. 阶段 0：安全网

### 任务 0A：补 Console 工作台组件行为测试

**文件：**
- 新建: `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`
- 阅读: `frontend/src/pages/console/ConsoleAppWorkspace.tsx:177-423`
- 阅读: `frontend/src/lib/api.test.ts`
- 阅读: `frontend/src/components/SecretDialog.test.tsx`

- [ ] **步骤 1：新增 MatrixTab 提交测试**

在 `ConsoleAppWorkspace.test.tsx` 中渲染 `/console/apps/demo?tab=matrix`，mock `apiRequest` 返回：

```ts
const matrixPayload = {
  version: "v1",
  roles: [{ id: 10, key: "admin", name: "管理员" }],
  permissions: [{ id: 20, key: "invoice.read", name: "发票读取" }],
  cells: [{ role_id: 10, permission_id: 20, enabled: false }],
};
```

断言勾选 `admin invoice.read` 后点击 `保存变更`，PATCH body 等于：

```ts
{
  base_version: "v1",
  assignments: [{ role_id: 10, permission_id: 20, enabled: true }],
  add: [],
  remove: [],
}
```

- [ ] **步骤 2：新增 CredentialsTab secret 测试**

mock `/credentials` 返回空列表，创建 `static-tokens` 返回：

```ts
{
  one_time_secret: {
    kind: "static_token",
    token: "plain-secret-once"
  }
}
```

断言弹出 `SecretDialog` 后关闭，`plain-secret-once` 不再出现在 DOM。

- [ ] **步骤 3：新增 OAuth client 操作测试**

mock credentials 返回 `kind: "oauth_client"` 与 `kind: "static_token"` 各一条；断言 OAuth client 行没有轮换按钮，禁用时调用 `/credentials/oauth-clients/{id}/disable`。

- [ ] **步骤 4：新增 QueryTestTab token 清空测试**

在 `/console/apps/demo?tab=test` 输入 `Bearer token`，mock 成功响应后断言密码输入框 value 变为空字符串。

- [ ] **步骤 5：运行前端目标测试**

运行:

```bash
pnpm --dir frontend test -- --run src/pages/console/ConsoleAppWorkspace.test.tsx
```

预期: 4 个新增用例通过。

### 任务 0B：补 OIDC 与认证失败路径测试

**文件：**
- 修改: `tests/integration/auth/test_oidc_exchange_s12.py`
- 修改: `tests/integration/api/test_authentication.py`
- 阅读: `src/easyauth/accounts/oidc_exchange.py:70-246`
- 阅读: `src/easyauth/api/authentication.py:30-56`

- [ ] **步骤 1：补 OIDC client_secret 为空测试**

新增用例：配置空 `client_secret`，调用 code exchange，断言抛 `OidcSessionError`，并断言 token endpoint mock 没有被调用。

- [ ] **步骤 2：补 token endpoint 失败矩阵**

新增参数化用例覆盖 `HTTPError`、`URLError`、非 JSON、JSON 非 object、缺少 `id_token`，统一断言返回 `OidcSessionError`，session 不写入 `AUTHENTIK_SESSION_KEY`。

- [ ] **步骤 3：补 JWKS 失败矩阵**

新增用例覆盖缺 matching `kid`、`alg` 不允许、JWK 非 RSA、缺 `n/e`，断言拒绝登录。

- [ ] **步骤 4：补 `AppBearerAuthentication` 直接单测**

覆盖 static token 失败后 OAuth fallback 返回 `AppPrincipal`、disabled app 抛 `PermissionDenied`、`Bearer` 无 token/无空格/多空白/大小写 scheme 的现有语义。

- [ ] **步骤 5：运行认证测试**

运行:

```bash
pytest tests/integration/auth/test_oidc_exchange_s12.py tests/integration/api/test_authentication.py tests/integration/oauth/test_client_credentials.py -q
```

预期: 全部通过。

### 任务 0C：补凭据 API 负向测试

**文件：**
- 修改: `tests/integration/admin_console/test_credentials_ops1.py`
- 修改: `tests/integration/admin_console/test_credentials_disable_ops1.py`
- 阅读: `src/easyauth/admin_console/credentials_api.py:50-180`
- 阅读: `src/easyauth/admin_console/credentials_disable_api.py:39-112`

- [ ] **步骤 1：补未登录测试**

覆盖 list/create/rotate/disable 未登录返回 401，数据库不创建/不修改凭据。

- [ ] **步骤 2：补 developer 权限测试**

覆盖 developer 对 rotate 和 disable 返回 403；已有 create forbidden 作为参考。

- [ ] **步骤 3：补输入边界测试**

覆盖 blank name、extra field、overlong name 返回 400 或 422，断言不创建凭据。

- [ ] **步骤 4：补跨 App credential_id 测试**

owner 在本 App 路径 rotate/disable 其他 App 的 credential，返回 404，目标凭据保持 active。

- [ ] **步骤 5：运行凭据测试**

运行:

```bash
pytest tests/integration/admin_console/test_credentials_ops1.py tests/integration/admin_console/test_credentials_disable_ops1.py -q
```

预期: 全部通过。

### 任务 0D：补 DingTalk 回调非法 payload 与冲突测试

**文件：**
- 修改: `tests/integration/integrations/test_dingtalk_callback.py`
- 阅读: `src/easyauth/integrations/dingtalk/callbacks.py:40-120`

- [ ] **步骤 1：补有效签名但 malformed JSON 测试**

断言返回 422，写入 `payload_rejected` 类审计事件，不创建授权。

- [ ] **步骤 2：补缺少 `process_instance_id` 测试**

断言返回 422，错误结构为 EasyAuth 标准错误响应。

- [ ] **步骤 3：补 unsupported status 测试**

断言返回 422，审计保留原始 payload 摘要。

- [ ] **步骤 4：补 approved 冲突状态测试**

当申请已是 `rejected` 或 `grant_failed`，approved 回调返回 409，不创建或修改授权。

- [ ] **步骤 5：运行 DingTalk 测试**

运行:

```bash
pytest tests/integration/integrations/test_dingtalk_callback.py -q
```

预期: 全部通过。

## 3. 阶段 1：低风险拆分

### 任务 1A：拆分全局 CSS P0 文件

**文件：**
- 修改: `frontend/src/main.tsx`
- 修改: `frontend/src/styles.css`
- 新建: `frontend/src/styles/tokens.css`
- 新建: `frontend/src/styles/layout-shell.css`
- 新建: `frontend/src/styles/components/buttons.css`
- 新建: `frontend/src/styles/components/table.css`
- 新建: `frontend/src/styles/components/forms.css`
- 新建: `frontend/src/styles/components/dialog-toast.css`
- 新建: `frontend/src/styles/features/workspace.css`
- 新建: `frontend/src/styles/features/permission-selector.css`
- 新建: `frontend/src/styles/features/matrix.css`
- 新建: `frontend/src/styles/responsive.css`

- [ ] **步骤 1：记录当前样式范围**

把 `frontend/src/styles.css` 按行号迁移：1-55 到 `tokens.css`；57-340 到 `layout-shell.css`；391-471 到 `buttons.css`；510-570 到 `table.css`；659-700 与 815-839 到 `forms.css`；872-971 到 `dialog-toast.css`；572-657 到 `workspace.css`；702-813 到 `permission-selector.css`；841-870 到 `matrix.css`；973-1068 到 `responsive.css`。

- [ ] **步骤 2：更新 `main.tsx` 导入顺序**

按如下顺序导入，保留 层叠顺序：

```ts
import "./styles/tokens.css";
import "./styles/layout-shell.css";
import "./styles/components/buttons.css";
import "./styles/components/table.css";
import "./styles/components/forms.css";
import "./styles/components/dialog-toast.css";
import "./styles/features/workspace.css";
import "./styles/features/permission-selector.css";
import "./styles/features/matrix.css";
import "./styles/responsive.css";
```

- [ ] **步骤 3：将 `styles.css` 改为聚合入口或删除**

若 `main.tsx` 已改为多文件导入，删除 `styles.css`；若保留单入口，则 `styles.css` 只保留上述 `@import`，且 SLOC 低于 30。

- [ ] **步骤 4：运行前端门禁**

运行:

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

预期: 全部通过。

### 任务 1B：抽 Portal 权限树纯函数

**文件：**
- 新建: `frontend/src/pages/portal/permissionTree.ts`
- 新建: `frontend/src/pages/portal/permissionTree.test.ts`
- 修改: `frontend/src/pages/portal/PortalPage.tsx:454-503`

- [ ] **步骤 1：新增纯函数测试**

测试 `filterGroupsByApp`、`collectPermissionKeys`、`isPermissionGroupItem`，覆盖子组、直接权限、跨 app 过滤、空 app 返回空树。

- [ ] **步骤 2：从 `PortalPage.tsx` 移出 454-503 行**

导出：

```ts
export function collectPermissionKeys(
  groups: PermissionGroupItem[],
  ungroupedPermissions: PermissionItem[],
): string[];
export function collectPermissions(groups: PermissionGroupItem[]): PermissionItem[];
export function collectGroupPermissions(group: PermissionGroupItem): PermissionItem[];
export function isPermissionGroupItem(item: PermissionGroupItem | PermissionItem): item is PermissionGroupItem;
export function filterGroupsByApp(groups: PermissionGroupItem[], appKey: string): PermissionGroupItem[];
export function filterGroupByApp(group: PermissionGroupItem, appKey: string): PermissionGroupItem | null;
export function filterPermissionByApp(permission: PermissionItem, appKey: string): PermissionItem | null;
```

- [ ] **步骤 3：更新 `PortalPage.tsx` import**

从 `./permissionTree` 导入上述函数，页面行为不变。

- [ ] **步骤 4：运行 Portal 前端测试**

运行:

```bash
pnpm --dir frontend test -- --run src/pages/portal/permissionTree.test.ts src/pages/portal/PortalPage.test.tsx
```

预期: 全部通过。

### 任务 1C：抽后端 API 通用辅助函数

**文件：**
- 新建: `src/easyauth/admin_console/api_responses.py`
- 新建: `src/easyauth/admin_console/authz.py`
- 新建: `src/easyauth/api/datetime_json.py`
- 修改: `src/easyauth/admin_console/operations_api.py`
- 修改: `src/easyauth/admin_console/operations_retry_api.py`
- 修改: `src/easyauth/admin_console/*_api.py` 中重复 `_error_response/_json_response` 的文件
- 修改: `src/easyauth/portal/access_request_data.py`
- 修改: `src/easyauth/admin_console/operations_payloads.py`

- [ ] **步骤 1：新增 `api_responses.py`**

提供 `error_response(code, message, details, status)` 和 `json_response(payload, status=HTTPStatus.OK)`，实现与现有 `_error_response/_json_response` 完全一致，`ensure_ascii=False`。

- [ ] **步骤 2：新增 `authz.py`**

提供 `require_superuser(request)`，迁移 `operations_api.py:181-195` 与 `operations_retry_api.py:211-225` 的现有行为。

- [ ] **步骤 3：新增 `datetime_json.py`**

提供：

```python
def datetime_value(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
```

- [ ] **步骤 4：逐文件替换重复辅助函数**

每次只改 1-2 个 API 文件，保持 import 清晰，删除本地重复函数。

- [ ] **步骤 5：运行 admin API 与 portal 目标测试**

运行:

```bash
pytest tests/integration/admin_console tests/integration/portal -q
ruff check src/easyauth tests
basedpyright
```

预期: 全部通过。

## 4. 阶段 2：组件/API 拆分

### 任务 2A：拆 `PortalPage.tsx`

**文件：**
- 修改: `frontend/src/pages/portal/PortalPage.tsx`
- 新建: `frontend/src/pages/portal/components/GrantTable.tsx`
- 新建: `frontend/src/pages/portal/components/RequestTable.tsx`
- 新建: `frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 新建: `frontend/src/pages/portal/components/PermissionSelector.tsx`

- [ ] **步骤 1：移动 `GrantTable`**

将 `PortalPage.tsx:46-75` 移到 `components/GrantTable.tsx`，导出 `GrantTable`，保持 属性 `endpoint` 和 `emptyText`。

- [ ] **步骤 2：移动 `RequestTable`**

将 `PortalPage.tsx:77-106` 移到 `components/RequestTable.tsx`。

- [ ] **步骤 3：移动 `PermissionSelector` 相关组件**

将 `PortalPage.tsx:279-452` 移到 `components/PermissionSelector.tsx`。

- [ ] **步骤 4：移动 `AccessRequestForm`**

将 `PortalPage.tsx:108-247` 移到 `components/AccessRequestForm.tsx`，从 `PermissionSelector` 和 `permissionTree.ts` 引入依赖。

- [ ] **步骤 5：运行 Portal 测试**

运行:

```bash
pnpm --dir frontend test -- --run src/pages/portal
pnpm --dir frontend typecheck
```

预期: 全部通过；`PortalPage.tsx` 降到 100 SLOC 以下。

### 任务 2B：拆 `ConsoleAppWorkspace.tsx`

**文件：**
- 修改: `frontend/src/pages/console/ConsoleAppWorkspace.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx`
- 新建: `frontend/src/pages/console/workspace/tabs/GuideTab.tsx`
- 新建: `frontend/src/pages/console/workspace/utils.ts`

- [ ] **步骤 1：移动 工具函数**

将 `flattenGroups`、`isPermissionGroup`、`safeJoin`、`credentialKindLabel` 移到 `workspace/utils.ts`。

- [ ] **步骤 2：按 tab 移动组件**

按原行号迁移：`OverviewTab` 93-123；`CatalogTab` 125-175；`MatrixTab` 177-261；`RulesTab` 263-281；`CredentialsTab` 283-383；`QueryTestTab` 385-423；`GuideTab` 425-448。

- [ ] **步骤 3：保留 shell 文件**

`ConsoleAppWorkspace.tsx` 只保留 `TABS`、route/searchParams、`PageHeader`、tabbar 和 tab 渲染。

- [ ] **步骤 4：运行工作台测试**

运行:

```bash
pnpm --dir frontend test -- --run src/pages/console/ConsoleAppWorkspace.test.tsx
pnpm --dir frontend typecheck
```

预期: 全部通过；`ConsoleAppWorkspace.tsx` 降到 120 SLOC 以下。

### 任务 2C：拆 `portal/api.py` catalog 和提交逻辑

**文件：**
- 修改: `src/easyauth/portal/api.py`
- 新建: `src/easyauth/portal/request_catalog.py`
- 新建: `src/easyauth/portal/access_request_payloads.py`
- 测试: `tests/integration/portal/test_request_catalog_api.py`
- 测试: `tests/integration/portal/test_access_request_s14.py`

- [ ] **步骤 1：移动 `_AccessRequestPayload` 与提交 target lookup**

将 `portal/api.py:50-59`、`216-249` 移到 `access_request_payloads.py`。

- [ ] **步骤 2：移动 catalog builder**

将 `portal/api.py:252-364` 移到 `request_catalog.py`，导出 `request_catalog_payload()`。

- [ ] **步骤 3：收缩 `portal/api.py`**

`portal_request_catalog` 只做 active user、method guard、调用 `request_catalog_payload()`、返回 JSON。

- [ ] **步骤 4：运行 portal 后端测试**

运行:

```bash
pytest tests/integration/portal/test_request_catalog_api.py tests/integration/portal/test_access_request_s14.py tests/integration/portal/test_portal_api_ops4.py -q
```

预期: 全部通过。

### 任务 2D：拆 `run_permission_query_test`

**文件：**
- 修改: `src/easyauth/admin_console/query_tester.py`
- 测试: `tests/integration/admin_console/test_query_tester_ops1.py`

- [ ] **步骤 1：提取 token 认证结果**

保留 `_authenticate_token`，新增 `_query_test_auth_error_result`，让认证失败分支返回结构更集中。

- [ ] **步骤 2：提取 app mismatch 检查**

新增 `_validate_principal_app(app, principal)`，返回 `PermissionQueryTestResult | None`。

- [ ] **步骤 3：提取权限查询执行**

新增 `_resolve_snapshot_result(app, user_id)`，把 `resolve_user_permissions` 和 `ValidationError` 映射移出主函数。

- [ ] **步骤 4：主函数只编排**

`run_permission_query_test` 保持参数和返回类型不变，SLOC 降到 40 以下。

- [ ] **步骤 5：运行联调测试**

运行:

```bash
pytest tests/integration/admin_console/test_query_tester_ops1.py -q
```

预期: 全部通过。

## 5. 阶段 3：边界修复

### 任务 3A：统一申请目标校验

**文件：**
- 新建: `src/easyauth/access_requests/target_validation.py`
- 修改: `src/easyauth/access_requests/application_target_validation.py`
- 修改: `src/easyauth/access_requests/submission_validation.py`
- 测试: `tests/unit/access_requests/test_services_ops4_application_target_stale.py`
- 测试: `tests/unit/access_requests/test_services_s14_validation.py`

- [ ] **步骤 1：抽 role/permission error builder**

把 `submission_validation.py:267-300` 与 `application_target_validation.py:12-48` 的重复规则集中到 `target_validation.py`。

- [ ] **步骤 2：保持现有错误消息**

迁移后错误消息保持：`Role must belong...`、`Role must be requestable.`、`Permission must not be deprecated.` 等完全一致。

- [ ] **步骤 3：替换两个调用方**

`submission_validation.py` 和 `application_target_validation.py` 只负责调用共享 validator 并转换异常类型。

- [ ] **步骤 4：运行 access request 测试**

运行:

```bash
pytest tests/unit/access_requests tests/integration/portal/test_access_request_s14.py -q
```

预期: 全部通过。

### 任务 3B：统一 portal 权限聚合

**文件：**
- 新建: `src/easyauth/portal/permission_aggregation.py`
- 修改: `src/easyauth/portal/api_data.py`
- 修改: `src/easyauth/portal/grant_rows.py`
- 测试: `tests/integration/portal/test_my_permissions_ops2.py`
- 测试: `tests/integration/portal/test_portal_api_ops2.py`

- [ ] **步骤 1：抽重复函数**

迁移 `_direct_permission_keys_by_grant_id`、`_role_permission_keys_by_role_id`、`_permission_keys` 到 `permission_aggregation.py`。

- [ ] **步骤 2：两个调用点复用**

`api_data.py` 与 `grant_rows.py` 删除本地重复函数，仅调用共享聚合函数。

- [ ] **步骤 3：运行 portal 授权展示测试**

运行:

```bash
pytest tests/integration/portal/test_my_permissions_ops2.py tests/integration/portal/test_portal_api_ops2.py tests/integration/portal/test_portal_api_ops4_permissions.py -q
```

预期: 全部通过。

### 任务 3C：收敛 DingTalk 外部回调边界

**文件：**
- 新建: `src/easyauth/access_requests/inbound_callbacks.py`
- 修改: `src/easyauth/integrations/dingtalk/callbacks.py`
- 测试: `tests/integration/integrations/test_dingtalk_callback.py`

- [ ] **步骤 1：新增入站服务**

`inbound_callbacks.py` 提供 `apply_approval_callback(process_instance_id, status, actor_id, raw_payload)`，内部调用 `AccessRequestService.apply_approved_access_request` 或拒绝流程。

- [ ] **步骤 2：瘦身 DingTalk callback**

`dingtalk/callbacks.py` 只保留签名校验、payload 解析、字段映射、调用入站服务、HTTP response 映射。

- [ ] **步骤 3：保持错误结构**

对 422、409、500 的现有 EasyAuth 错误响应结构不变。

- [ ] **步骤 4：运行 DingTalk 测试**

运行:

```bash
pytest tests/integration/integrations/test_dingtalk_callback.py -q
```

预期: 全部通过。

### 任务 3D：修复 `applications` 包级引导耦合

**文件：**
- 修改: `src/easyauth/applications/models.py:9`
- 修改: `src/easyauth/applications/ops_models.py:10`
- 修改: `src/easyauth/applications/__init__.py:9-15`
- 测试: `tests/unit/applications/test_models.py`

- [ ] **步骤 1：改显式子模块导入**

将 `from easyauth.applications import oauth_models, ops_models` 改成同包显式导入，避免包入口回绕。

- [ ] **步骤 2：检查 `__init__.py` 导出必要性**

如果仅为 Django model discovery，保留最小导入；如果没有运行时引用，删除中转别名。

- [ ] **步骤 3：运行 Django 启动和应用测试**

运行:

```bash
.venv/bin/python manage.py check
.venv/bin/pytest tests/unit/applications tests/integration/admin_console/test_dependency_health_ops3.py -q
```

预期: 全部通过。

## 6. 阶段质量门禁

命令约定：如果 `.venv/bin` 存在，后端命令优先使用 `.venv/bin/python`、`.venv/bin/pytest`、`.venv/bin/ruff`、`.venv/bin/basedpyright`；如果执行环境没有项目虚拟环境，再使用 `python3`、`pytest`、`ruff`、`basedpyright`。

### 阶段 0 门禁

```bash
pnpm --dir frontend test -- --run src/pages/console/ConsoleAppWorkspace.test.tsx
.venv/bin/pytest tests/integration/auth/test_oidc_exchange_s12.py tests/integration/api/test_authentication.py tests/integration/oauth/test_client_credentials.py -q
.venv/bin/pytest tests/integration/admin_console/test_credentials_ops1.py tests/integration/admin_console/test_credentials_disable_ops1.py -q
.venv/bin/pytest tests/integration/integrations/test_dingtalk_callback.py -q
```

### 阶段 1 门禁

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
pnpm --dir frontend build
.venv/bin/pytest tests/integration/admin_console tests/integration/portal -q
.venv/bin/ruff check src/easyauth tests
.venv/bin/basedpyright
```

### 阶段 2 门禁

```bash
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
.venv/bin/pytest tests/integration/portal tests/integration/admin_console/test_query_tester_ops1.py -q
```

### 阶段 3 门禁

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/pytest tests/unit/access_requests tests/integration/portal tests/integration/integrations/test_dingtalk_callback.py tests/unit/applications -q
.venv/bin/ruff check src/easyauth tests
.venv/bin/basedpyright
```

### 最终门禁

```bash
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py migrate --check
.venv/bin/pytest -q
.venv/bin/ruff check src/easyauth tests
.venv/bin/basedpyright
pnpm --dir frontend typecheck
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

## 7. 子代理分派建议

每个子代理只拿一个任务，禁止同阶段两个子代理改同一文件。

| 子代理 | 阶段 | 写范围 | 输出 |
|---|---|---|---|
| frontend-test-agent | 阶段 0A | `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx` | 新组件测试与运行结果 |
| auth-test-agent | 阶段 0B | `tests/integration/auth/*`、`tests/integration/api/test_authentication.py` | 认证失败矩阵 |
| credential-test-agent | 阶段 0C | `tests/integration/admin_console/test_credentials*.py` | 凭据负向测试 |
| dingtalk-test-agent | 阶段 0D | `tests/integration/integrations/test_dingtalk_callback.py` | 回调非法输入测试 |
| css-agent | 阶段 1A | `frontend/src/styles/**`、`frontend/src/main.tsx` | CSS 拆分 |
| portal-frontend-agent | 阶段 1B/2A | `frontend/src/pages/portal/**` | Portal 组件拆分 |
| admin-helper-agent | 阶段 1C | `src/easyauth/admin_console/*`、`src/easyauth/api/datetime_json.py` | 通用辅助函数 |
| console-frontend-agent | 阶段 2B | `frontend/src/pages/console/**` | Console tab 拆分 |
| portal-api-agent | 阶段 2C/3B | `src/easyauth/portal/**` | portal API 与聚合 |
| access-request-agent | 阶段 3A | `src/easyauth/access_requests/**` | 目标校验统一 |
| dingtalk-boundary-agent | 阶段 3C | `src/easyauth/integrations/dingtalk/callbacks.py`、`src/easyauth/access_requests/inbound_callbacks.py` | 回调边界 |
| applications-agent | 阶段 3D | `src/easyauth/applications/**` | 包导入修复 |

## 8. 冲突与回滚策略

- `frontend/src/pages/portal/PortalPage.tsx`：阶段 1B 和 阶段 2A 不能并行；先抽纯函数，再拆组件。
- `frontend/src/pages/console/ConsoleAppWorkspace.tsx`：阶段 0A 只写测试；阶段 2B 才拆生产文件。
- `src/easyauth/portal/api_data.py` 与 `src/easyauth/portal/grant_rows.py`：只由 任务 3B 修改，避免和 任务 2C 冲突。
- `src/easyauth/admin_console/*_api.py`：任务 1C 涉及多个文件，执行时按文件小批量提交。
- 每个任务以一个提交为回滚单位；如果阶段门禁失败，先回滚最近任务提交，不跨阶段回滚。

## 9. 完成定义

- `frontend/src/styles.css` 不再超过 500 SLOC；若删除则所有样式通过分文件导入。
- `PortalPage.tsx` 和 `ConsoleAppWorkspace.tsx` 均低于 180 SLOC，页面 shell 与业务 tab/组件分离。
- `run_permission_query_test` 低于 40 SLOC。
- 重复 `_error_response/_json_response`、`_require_superuser`、`_datetime_value` 被统一。
- portal 权限聚合和 access request 目标校验只有一个规则来源。
- DingTalk 集成层不直接承担申请状态变更业务逻辑。
- 最终门禁全部通过。
