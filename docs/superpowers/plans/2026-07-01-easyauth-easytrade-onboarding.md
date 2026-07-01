# EasyAuth 接入 EasyTrade 运营实施计划

> **面向 agentic workers:** REQUIRED SUB-SKILL: 实施本计划时使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐任务执行并用 checkbox 更新状态。

**目标:** 在 EasyAuth 中完成 `easytrade` App、权限目录、授权组、审批规则、凭据和联调能力的运营落地。

**架构:** EasyAuth 作为授权事实源，只暴露统一公共查询契约。EasyTrade 的角色语义用 `AuthorizationGroup(kind="role")` 表达，能力包用 `AuthorizationGroup(kind="bundle")` 表达，最终授权事实由 `AccessGrantGroup` 和 `AccessGrantPermission` 展开为 `permission + scope` grants。

**技术栈:** Django 5、Django REST Framework 风格 JSON API、Pydantic、React/Vite、pytest、Vitest、Playwright。

**执行记录（2026-07-01）:** 本次使用本地开发登录 `easytrade-owner`、真实 HTTP API、EasyTrade Docker backend 生成的 `/tmp/easytrade-easyauth-manifest.json` 和 EasyAuth `127.0.0.1:8010` Django 服务完成自动化运营落地。控制台页面通过真实 HTTP 和前端测试验证；未人工点击“新建应用”弹窗，因此该手动 UI 步骤保留未勾选。

---

## 文件结构

- 修改或验证: `src/easyauth/admin_console/apps_api.py`
  - 负责 `GET|POST /console/api/v1/apps` 和 `GET|PATCH /console/api/v1/apps/{app_key}`。
- 修改或验证: `src/easyauth/admin_console/permission_template_api.py`
  - 负责 manifest 预览、确认导入、版本列表和导出。
- 修改或验证: `src/easyauth/applications/permission_template_parsing.py`
  - 负责 manifest schema 解析和引用校验。
- 修改或验证: `src/easyauth/applications/permission_template_storage.py`
  - 负责写入 `AppScope`、`PermissionGroup`、`Permission`、`AuthorizationGroup`、`AuthorizationGroupGrant`、`ApprovalRule`。
- 修改或验证: `src/easyauth/admin_console/authorization_groups_api.py`
  - 负责授权组配置 API。
- 修改或验证: `src/easyauth/admin_console/approval_rules_api.py`
  - 负责审批规则配置 API。
- 修改或验证: `src/easyauth/admin_console/credentials_api.py`
  - 负责 static token 和 OAuth client credentials 创建。
- 修改或验证: `src/easyauth/api/views.py`
  - 负责公共权限查询，不允许为 EasyTrade 增加专用响应格式。
- 修改或验证: `src/easyauth/grants/query.py`
  - 负责把 `AccessGrantGroup` 和 `AccessGrantPermission` 展开为 `groups` 和 `grants`。
- 修改或验证: `frontend/src/pages/console/ConsoleAppList.tsx`
  - 负责控制台新建 App 入口。
- 修改或验证: `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx`
  - 负责 manifest 上传、粘贴、预览、确认导入和版本展示。
- 修改或验证: `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
  - 负责 scope、permission group、permission 的目录维护。
- 修改或验证: `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
  - 负责 `AuthorizationGroup` 与 grants 的管理。
- 修改或验证: `frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
  - 负责审批规则管理。
- 修改或验证: `frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx`
  - 负责凭据创建、轮换和禁用。
- 修改或验证: `frontend/src/pages/console/workspace/tabs/QueryTestTab.tsx`
  - 负责真实公共查询联调。

## 统一契约

公共查询 API 保持如下响应形状：

```json
{
  "user_id": "ak_uid_001",
  "app_key": "easytrade",
  "groups": [
    {"key": "sales", "kind": "role", "name": "销售"}
  ],
  "grants": [
    {
      "permission": "customer.profile.view",
      "scope": "SELF",
      "source_type": "group",
      "source_key": "sales"
    }
  ],
  "grant_version": 12,
  "catalog_version": 4,
  "snapshot_version": "12.4",
  "expires_at": "2026-07-01T12:00:00+08:00"
}
```

EasyAuth 不提供 `userId/appKey/version/expiresAt` 兼容响应。下游需要在 EasyTrade 侧适配统一 snake_case 契约。

---

### Task 1: 创建 `easytrade` App

**Files:**
- Verify: `src/easyauth/admin_console/apps_api.py`
- Verify: `frontend/src/pages/console/ConsoleAppList.tsx`
- Test: `tests/integration/admin_console/test_apps_api_ops1.py`
- Test: `frontend/src/pages/console/ConsoleAppList.test.tsx`

- [x] **Step 1: 用 API 创建 App**

使用已登录的系统管理员 session 发起请求：

```bash
curl -X POST http://127.0.0.1:8000/console/api/v1/apps \
  -H 'Content-Type: application/json' \
  -H "X-CSRFToken: $EASYAUTH_CSRF_TOKEN" \
  -b "$EASYAUTH_SESSION_COOKIE" \
  --data '{
    "app_key": "easytrade",
    "name": "EasyTrade",
    "description": "外贸单据与客户管理中心",
    "is_active": true,
    "owner_user_ids": ["easytrade-owner"],
    "developer_user_ids": ["easytrade-developer"]
  }'
```

Expected: HTTP 201，响应包含 `app.app_key == "easytrade"`，`owners` 包含 `easytrade-owner`。

- [ ] **Step 2: 用控制台创建同等 App**

打开 `/console`，点击“新建应用”，填写：

```text
app_key: easytrade
名称: EasyTrade
描述: 外贸单据与客户管理中心
Owner 用户 ID: easytrade-owner
Developer 用户 ID: easytrade-developer
状态: 启用应用
```

Expected: 创建后跳转到 `/console/apps/easytrade`。

- [x] **Step 3: 跑 App API 和前端单测**

```bash
uv run pytest tests/integration/admin_console/test_apps_api_ops1.py -q
pnpm --dir frontend test -- ConsoleAppList.test.tsx
```

Expected: 两条命令通过。若本机没有 `uv`，在 EasyAuth 的项目虚拟环境中执行等价 `pytest` 命令。

- [x] **Step 4: 验证配置状态**

```bash
curl http://127.0.0.1:8000/console/api/v1/apps/easytrade/configuration-status \
  -b "$EASYAUTH_SESSION_COOKIE"
```

Expected: 初始状态允许为 `blocking`，原因应明确指向缺少目录、授权组、审批规则或凭据，不允许返回不透明错误。

- [x] **Step 5: 提交 EasyAuth 侧必要调整**

只有在本任务修改代码或测试时提交：

```bash
git add src/easyauth/admin_console/apps_api.py frontend/src/pages/console/ConsoleAppList.tsx tests/integration/admin_console/test_apps_api_ops1.py frontend/src/pages/console/ConsoleAppList.test.tsx
git commit -m "feat(console): support EasyTrade app onboarding"
```

---

### Task 2: 导入 EasyTrade manifest

**Files:**
- Verify: `src/easyauth/applications/permission_template_parsing.py`
- Verify: `src/easyauth/applications/permission_template_storage.py`
- Verify: `src/easyauth/admin_console/permission_template_api.py`
- Verify: `frontend/src/pages/console/workspace/tabs/ManifestTab.tsx`
- Test: `tests/unit/applications/test_permission_templates_ops1.py`
- Test: `tests/integration/admin_console/test_template_guide_api_ops1.py`

- [x] **Step 1: 使用首版 manifest 内容**

首版 manifest 应由 EasyTrade 的导出工具生成。手工联调时可先使用以下最小样例：

```json
{
  "schema_version": 1,
  "app": {
    "app_key": "easytrade",
    "name": "EasyTrade",
    "description": "外贸单据与客户管理中心"
  },
  "scopes": [
    {"key": "SELF", "name": "本人", "description": "本人 owner 范围", "display_order": 10},
    {"key": "MANAGED", "name": "管理范围", "description": "本人、同 region 或同 segment 的 active 用户", "display_order": 20},
    {"key": "ALL", "name": "全部", "description": "不按 owner 过滤", "display_order": 30}
  ],
  "permission_groups": [
    {"key": "customer", "name": "客户", "description": "", "parent_key": "", "display_order": 10},
    {"key": "pipeline", "name": "Pipeline", "description": "", "parent_key": "", "display_order": 20}
  ],
  "permissions": [
    {
      "key": "customer.profile.view",
      "name": "查看客户",
      "description": "",
      "group_key": "customer",
      "supported_scopes": ["SELF", "MANAGED", "ALL"],
      "risk_level": "standard"
    },
    {
      "key": "pipeline.inquiry.view",
      "name": "查看 Pipeline",
      "description": "",
      "group_key": "pipeline",
      "supported_scopes": ["SELF", "MANAGED", "ALL"],
      "risk_level": "standard"
    }
  ],
  "authorization_groups": [
    {
      "key": "sales",
      "kind": "role",
      "name": "销售",
      "description": "销售角色预置授权组",
      "requestable": true,
      "is_active": true,
      "grants": [
        {"permission": "customer.profile.view", "scope": "SELF"},
        {"permission": "pipeline.inquiry.view", "scope": "SELF"}
      ]
    }
  ],
  "approval_rules": [
    {
      "target_type": "authorization_group",
      "target_key": "sales",
      "approver_userids": ["easytrade-owner"],
      "is_active": true
    }
  ]
}
```

- [x] **Step 2: 预览 manifest**

```bash
curl -X POST http://127.0.0.1:8000/console/api/v1/apps/easytrade/permission-template-imports/preview \
  -H 'Content-Type: application/json' \
  -H "X-CSRFToken: $EASYAUTH_CSRF_TOKEN" \
  -b "$EASYAUTH_SESSION_COOKIE" \
  --data "{\"template_format\":\"json\",\"template\":$(jq -Rs . /tmp/easytrade-easyauth-manifest.json)}"
```

Expected: HTTP 200，响应包含 `preview_id`，并列出将创建的 scope、permission group、permission、authorization group、approval rule。数据库不应写入这些目录对象。

- [x] **Step 3: 确认导入**

```bash
curl -X POST "http://127.0.0.1:8000/console/api/v1/apps/easytrade/permission-template-imports/$EASYAUTH_MANIFEST_PREVIEW_ID/confirm" \
  -H "X-CSRFToken: $EASYAUTH_CSRF_TOKEN" \
  -b "$EASYAUTH_SESSION_COOKIE"
```

Expected: HTTP 200，`catalog_version` 提升，`PermissionTemplateVersion.version == 1`。

- [x] **Step 4: 导出并回放校验**

```bash
curl http://127.0.0.1:8000/console/api/v1/apps/easytrade/manifest \
  -b "$EASYAUTH_SESSION_COOKIE"
```

Expected: 导出内容包含 `scopes`、`permission_groups`、`permissions`、`authorization_groups`、`approval_rules`，不包含 token、client secret 或任何用户授权事实。

- [x] **Step 5: 跑 manifest 测试**

```bash
uv run pytest tests/unit/applications/test_permission_templates_ops1.py tests/integration/admin_console/test_template_guide_api_ops1.py -q
pnpm --dir frontend test -- ConsoleAppWorkspace.test.tsx
```

Expected: 全部通过。

- [x] **Step 6: 提交 EasyAuth 侧必要调整**

只有在本任务修改代码或测试时提交：

```bash
git add src/easyauth/applications/permission_template_parsing.py src/easyauth/applications/permission_template_storage.py src/easyauth/admin_console/permission_template_api.py frontend/src/pages/console/workspace/tabs/ManifestTab.tsx tests/unit/applications/test_permission_templates_ops1.py tests/integration/admin_console/test_template_guide_api_ops1.py
git commit -m "feat(manifest): support EasyTrade catalog import"
```

---

### Task 3: 配置授权组和审批规则

**Files:**
- Verify: `src/easyauth/admin_console/authorization_groups_api.py`
- Verify: `src/easyauth/admin_console/approval_rules_api.py`
- Verify: `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- Verify: `frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- Test: `tests/integration/admin_console/test_approval_rules_api_ops1.py`
- Test: `tests/unit/grants/test_query.py`

- [x] **Step 1: 检查授权组语义**

确认 EasyTrade 的预置角色全部用 `AuthorizationGroup(kind="role")` 表达：

```json
[
  {"key": "sales", "kind": "role", "name": "销售"},
  {"key": "sales_manager", "kind": "role", "name": "销售经理"},
  {"key": "admin", "kind": "role", "name": "管理员"}
]
```

Expected: 不创建旧 `Role`，不使用 `RolePermission` 作为新接入主路径。

- [x] **Step 2: 检查能力包语义**

跨角色能力包用 `AuthorizationGroup(kind="bundle")` 表达：

```json
[
  {"key": "bundle_customer_readonly", "kind": "bundle", "name": "客户只读包"},
  {"key": "bundle_pipeline_ops", "kind": "bundle", "name": "Pipeline 操作包"}
]
```

Expected: `bundle` 可作为用户 grant target，但不得替代 `PermissionGroup`。`PermissionGroup` 仍只表示目录树。

- [x] **Step 3: 配置审批规则**

每个 `requestable=true` 的授权组至少有一条 active approval rule：

```json
{
  "target_type": "authorization_group",
  "target_key": "sales",
  "approver_userids": ["easytrade-owner"],
  "is_active": true
}
```

Expected: `configuration-status` 不再报告 `requestable_authorization_group_approval_rule_missing`。

- [x] **Step 4: 跑授权展开测试**

```bash
uv run pytest tests/unit/grants/test_query.py tests/integration/admin_console/test_approval_rules_api_ops1.py -q
```

Expected: `resolve_user_permissions` 只从 `AccessGrantGroup -> AuthorizationGroupGrant` 和 `AccessGrantPermission` 展开 grants。

- [x] **Step 5: 提交 EasyAuth 侧必要调整**

只有在本任务修改代码或测试时提交：

```bash
git add src/easyauth/admin_console/authorization_groups_api.py src/easyauth/admin_console/approval_rules_api.py frontend/src/pages/console/workspace/tabs/MatrixTab.tsx frontend/src/pages/console/workspace/tabs/RulesTab.tsx tests/integration/admin_console/test_approval_rules_api_ops1.py tests/unit/grants/test_query.py
git commit -m "feat(authz): configure EasyTrade authorization groups"
```

---

### Task 4: 创建凭据并验证公共查询

**Files:**
- Verify: `src/easyauth/admin_console/credentials_api.py`
- Verify: `src/easyauth/admin_console/query_test_api.py`
- Verify: `src/easyauth/admin_console/console_app_api.py`
- Verify: `src/easyauth/api/views.py`
- Verify: `src/easyauth/api/serializers.py`
- Test: `tests/integration/admin_console/test_credentials_ops1.py`
- Test: `tests/integration/admin_console/test_query_tester_ops1.py`
- Test: `tests/integration/api/test_permission_query_ops1.py`

- [x] **Step 1: 创建 static token**

```bash
curl -X POST http://127.0.0.1:8000/console/api/v1/apps/easytrade/credentials/static-tokens \
  -H 'Content-Type: application/json' \
  -H "X-CSRFToken: $EASYAUTH_CSRF_TOKEN" \
  -b "$EASYAUTH_SESSION_COOKIE" \
  --data '{"name":"EasyTrade production query token"}'
```

Expected: HTTP 201，响应只在本次返回明文 token。列表接口只能返回 token metadata。

- [x] **Step 2: 用联调页查询用户**

在 `/console/apps/easytrade` 的联调页输入 EasyAuth 用户 ID，例如：

```text
ak_uid_sales_001
```

Expected: 联调页展示 `groups`、`grants`、`grant_version`、`catalog_version`、`snapshot_version`、`expires_at`。

- [x] **Step 3: 直接调用公共查询**

```bash
curl http://127.0.0.1:8000/api/v1/apps/easytrade/users/ak_uid_sales_001/permissions \
  -H "Authorization: Bearer $EASYTRADE_EASYAUTH_TOKEN"
```

Expected: HTTP 200，字段为 snake_case 统一契约；如果用户没有授权，`groups` 和 `grants` 为空数组，仍返回 `snapshot_version` 和 `expires_at`。

- [x] **Step 4: 跑凭据和公共查询测试**

```bash
uv run pytest tests/integration/admin_console/test_credentials_ops1.py tests/integration/admin_console/test_query_tester_ops1.py tests/integration/api/test_permission_query_ops1.py -q
```

Expected: 全部通过。

- [x] **Step 5: 完成控制台页面验证**

如果本任务修改了 Django 后端、模板、React 或 Vite build 产物，必须重启当前 Django 开发服务，然后验证真实页面：

```bash
curl -I http://127.0.0.1:8000/console/apps/easytrade/
curl -I http://127.0.0.1:8000/console/
```

Expected: 两个 URL 都返回 200 或登录重定向，且浏览器里能看到最新 React 页面。

- [x] **Step 6: 提交 EasyAuth 侧必要调整**

只有在本任务修改代码或测试时提交：

```bash
git add src/easyauth/admin_console/credentials_api.py src/easyauth/admin_console/query_test_api.py src/easyauth/admin_console/console_app_api.py src/easyauth/api/views.py src/easyauth/api/serializers.py tests/integration/admin_console/test_credentials_ops1.py tests/integration/admin_console/test_query_tester_ops1.py tests/integration/api/test_permission_query_ops1.py
git commit -m "feat(credentials): enable EasyTrade permission query"
```

---

## 禁止事项

- 不要给 EasyTrade 增加专用公共响应 envelope。
- 不要恢复旧 `Role` / `RolePermission` 作为新接入主路径。
- 不要把 `PermissionGroup` 作为授权对象、审批对象或申请对象。
- 不要绕过 `GrantService` 或现有领域服务直接写授权事实。
- 不要在导出 manifest、凭据列表、审计日志或前端页面里暴露 static token 明文或 OAuth client secret。
- 不要用静默 fallback 掩盖 manifest 引用错误、scope 错误、凭据错误或 grant 展开错误。

## 总体验收

```bash
uv run pytest tests/unit/applications/test_permission_templates_ops1.py tests/unit/grants/test_query.py tests/integration/admin_console/test_apps_api_ops1.py tests/integration/admin_console/test_template_guide_api_ops1.py tests/integration/admin_console/test_credentials_ops1.py tests/integration/admin_console/test_query_tester_ops1.py tests/integration/api/test_permission_query_ops1.py -q
pnpm --dir frontend test -- ConsoleAppList.test.tsx ConsoleAppWorkspace.test.tsx PortalPage.test.tsx
pnpm --dir frontend typecheck
```

Expected: 目标测试通过；如果修改了运行页面相关文件，重启 Django 开发服务并用真实 `/console` 页面验证。
