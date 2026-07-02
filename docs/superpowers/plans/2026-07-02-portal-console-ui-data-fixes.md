# Portal 与 Console 修复实施计划

> **给代理执行者：** 必需子技能：使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务执行本计划。步骤使用复选框（`- [ ]`）语法跟踪。

**目标：** 修复 portal 申请权限页的数据口径、文案和布局问题，并修复 console 应用列表、应用工作台 tab、表格按钮和运营页权限态问题。

**架构：** 后端以真实数据库模型为唯一数据源，不引入 mock、静默 fallback 或长期兼容层。portal 目录接口只返回可真实提交的申请目标；console 前端只调用已有或新增的真实 API；表格按钮通过共享 action primitive 收敛到 EasyTrade 的行内操作风格。

**技术栈：** Django 5.2、Pydantic、React 19、TanStack Query、TanStack Table、Vitest、Playwright、pytest。

---

## 已确认根因

- portal 页头说明在 `frontend/src/pages/portal/PortalPage.tsx` 的 `PageHeader.description`。
- portal 申请页运行时代码没有 mock；数据来自 `GET /portal/api/v1/request-catalog`。
- portal request catalog 的 `AuthorizationGroup` 查询只过滤 `app__is_active=True`、`is_active=True`、`requestable=True`，没有过滤 active `ApprovalRule`，但提交阶段会校验 active approval rule，导致目录和提交结果不一致。
- portal 与 console 的目录本来是不同视角：console 是管理视角，portal 是员工可申请视角；本次修复要让 portal 只显示真实可申请目标，并用测试暴露后端真实筛选问题。
- console 应用启用/停用已有 `PATCH /console/api/v1/apps/<app_key>`，删除应用 API 当前不存在。
- console 运营页无条件 `useQuery`，后端 `require_superuser` 返回 403，所以非管理员先看到 loading 再看到失败。
- EasyTrade 表格行内按钮风格由 `GridActionCell` + `Button size="sm" variant="ghost|ghost-danger"` 约束；EasyAuth 缺少等价表格 action primitive。

## 影响文件

- 修改：`src/easyauth/portal/request_catalog.py`
- 修改：`tests/integration/portal/test_request_catalog_api.py`
- 修改：`frontend/src/pages/portal/PortalPage.tsx`
- 修改：`frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 修改：`frontend/src/pages/portal/components/RequestTargetPicker.tsx`
- 修改：`frontend/src/pages/portal/components/AccessRequestFields.tsx`
- 修改：`frontend/src/pages/portal/PortalPage.test.tsx`
- 修改：`frontend/e2e/smoke.spec.ts`
- 修改：`src/easyauth/admin_console/apps_api.py`
- 修改：`src/easyauth/admin_console/urls.py`
- 修改：`tests/integration/admin_console/test_apps_api_ops1.py`
- 修改：`frontend/src/components/Button.tsx`
- 新增：`frontend/src/components/ui/TableActions.tsx`
- 修改：`frontend/src/components/ui/PageState.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppList.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppList.test.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppWorkspace.tsx`
- 修改：`frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`
- 修改：`frontend/src/pages/console/OperationsPage.tsx`
- 新增：`frontend/src/pages/console/OperationsPage.test.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/OverviewTab.tsx`
- 修改：`frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- 视情况修改：`frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx`

---

### 任务 1: 修正 portal 申请目录真实口径

**文件：**
- 修改： `src/easyauth/portal/request_catalog.py`
- 修改： `tests/integration/portal/test_request_catalog_api.py`

- [ ] **步骤 1: 写失败测试，证明无 active ApprovalRule 的授权组不会进入 portal 目录**

在 `tests/integration/portal/test_request_catalog_api.py` 增加测试：

```python
def test_portal_request_catalog_excludes_requestable_group_without_active_approval_rule() -> None:
    client, _user = logged_in_client("request-catalog-no-rule-user")
    app_without_rule = App.objects.create(app_key="catalog-no-rule", name="No Rule")
    app_with_rule = App.objects.create(app_key="catalog-with-rule", name="With Rule")
    group_without_rule = AuthorizationGroup.objects.create(
        app=app_without_rule,
        key="reader",
        kind="role",
        name="无审批规则角色",
        requestable=True,
    )
    group_with_rule = AuthorizationGroup.objects.create(
        app=app_with_rule,
        key="auditor",
        kind="role",
        name="有审批规则角色",
        requestable=True,
    )
    _ = ApprovalRule.objects.create(
        app=app_with_rule,
        authorization_group=group_with_rule,
        approver_userids=["manager-001"],
    )

    response = client.get(REQUEST_CATALOG_URL)

    body = response.content.decode()
    payload = json_object(response)
    assert response.status_code == HTTPStatus.OK
    assert group_with_rule.key in body
    assert group_without_rule.key not in body
    assert payload["apps"] == [
        {
            "id": app_with_rule.id,
            "app_key": app_with_rule.app_key,
            "name": app_with_rule.name,
            "description": app_with_rule.description,
            "catalog_version": app_with_rule.catalog_version,
        },
    ]
```

- [ ] **步骤 2: 运行测试，确认当前实现失败**

运行：

```bash
uv run pytest tests/integration/portal/test_request_catalog_api.py::test_portal_request_catalog_excludes_requestable_group_without_active_approval_rule -q
```

预期： FAIL，响应中仍包含无 active ApprovalRule 的 group 或 app。

- [ ] **步骤 3: 修改 `_request_catalog_authorization_groups`**

在 `src/easyauth/portal/request_catalog.py` 中把查询改为按 active approval rule 过滤：

```python
def _request_catalog_authorization_groups() -> tuple[AuthorizationGroup, ...]:
    return tuple(
        AuthorizationGroup.objects.select_related("app")
        .filter(
            app__is_active=True,
            is_active=True,
            requestable=True,
            approval_rules__is_active=True,
        )
        .distinct()
        .order_by("app__app_key", "kind", "key"),
    )
```

- [ ] **步骤 4: 运行 portal 目录测试**

运行：

```bash
uv run pytest tests/integration/portal/test_request_catalog_api.py -q
```

预期： PASS。

---

### 任务 2: 重排 portal 申请权限 UI 并删除指定文案

**文件：**
- 修改： `frontend/src/pages/portal/PortalPage.tsx`
- 修改： `frontend/src/pages/portal/components/AccessRequestForm.tsx`
- 修改： `frontend/src/pages/portal/components/RequestTargetPicker.tsx`
- 修改： `frontend/src/pages/portal/components/AccessRequestFields.tsx`
- 修改： `frontend/src/pages/portal/PortalPage.test.tsx`
- 修改： `frontend/e2e/smoke.spec.ts`

- [ ] **步骤 1: 改测试定位方式，避免依赖 combobox 下标**

将 `PortalPage.test.tsx` 中 `screen.getAllByRole("combobox")[0]`、`[1]`、`[2]` 改成 label 定位，例如：

```ts
await user.selectOptions(screen.getByLabelText("应用"), "crm");
await user.selectOptions(screen.getByLabelText("可申请权限组"), "reader");
await user.selectOptions(screen.getByLabelText("授权期限"), "timed");
```

预期： 只改定位，不改断言语义。

- [ ] **步骤 2: 删除 portal 每页页头说明**

在 `frontend/src/pages/portal/PortalPage.tsx` 中删除 `PageHeader` 的 `description` 属性：

```tsx
<PageHeader eyebrow="Portal" title={viewTitle(view)} />
```

- [ ] **步骤 3: 拆分左栏和右栏字段职责**

将 `RequestTargetPicker` 改为只渲染：

```tsx
<>
  <Field label="应用">
    <SelectInput value={appKey} onChange={(event) => onAppKeyChange(event.currentTarget.value)}>
      <option value="">选择应用</option>
      {apps.map((app) => (
        <option key={app.app_key} value={app.app_key}>
          {app.name} ({app.app_key})
        </option>
      ))}
    </SelectInput>
  </Field>
  <Field
    label="直接权限"
    hint={appKey ? `已选 ${selectedPermissionKeys.length} 项直接权限，可留空。` : "请先选择应用后再选择直接权限。"}
  >
    <PermissionSelector
      appKey={appKey}
      groups={permissionGroups}
      ungroupedPermissions={ungroupedPermissions}
      selectedKeys={selectedPermissionKeys}
      selectedScopes={selectedPermissionScopes}
      expandedGroupKeys={expandedGroupKeys}
      loading={catalogIsLoading}
      errorMessage={catalogErrorMessage}
      onTogglePermission={onTogglePermission}
      onPermissionScopeChange={onPermissionScopeChange}
      onToggleGroup={onToggleGroup}
    />
  </Field>
</>
```

同时删除 `“来自员工门户可申请目录。”` 和 `“展示 active、requestable 且有审批规则的 role 或 bundle。”`。

- [ ] **步骤 4: 将可申请权限组移入右栏**

把 `AccessRequestFields` props 扩展为接收 `appKey`、`authorizationGroupKey`、`authorizationGroups`、`onAuthorizationGroupKeyChange`，在右栏顶部渲染：

```tsx
<Field label="可申请权限组">
  <SelectInput
    value={authorizationGroupKey}
    onChange={(event) => onAuthorizationGroupKeyChange(event.currentTarget.value)}
    disabled={!appKey}
  >
    <option value="">不选择权限组</option>
    {authorizationGroups.map((group) => (
      <option key={`${group.app_key}:${group.key}`} value={group.key}>
        {group.name} [{group.kind}] ({group.key})
      </option>
    ))}
  </SelectInput>
</Field>
```

- [ ] **步骤 5: 过期时间不可用时置灰但不消失**

在 `AccessRequestFields` 中始终渲染过期时间：

```tsx
<Field label="过期时间">
  <TextInput
    type="datetime-local"
    value={expiresAt}
    onChange={(event) => onExpiresAtChange(event.currentTarget.value)}
    disabled={grantType !== "timed"}
  />
</Field>
```

- [ ] **步骤 6: 确认左右栏结构**

在 `AccessRequestForm.tsx` 中保持两栏网格，但传参改为：

```tsx
<div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(320px,0.65fr)]">
  <RequestTargetPicker ... />
  <AccessRequestFields
    appKey={form.appKey}
    authorizationGroupKey={form.authorizationGroupKey}
    authorizationGroups={form.authorizationGroups}
    grantType={form.grantType}
    expiresAt={form.expiresAt}
    reason={form.reason}
    onAuthorizationGroupKeyChange={form.changeAuthorizationGroupKey}
    onGrantTypeChange={form.changeGrantType}
    onExpiresAtChange={form.changeExpiresAt}
    onReasonChange={form.changeReason}
  />
</div>
```

- [ ] **步骤 7: 运行前端 portal 测试**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx
pnpm --dir frontend typecheck
```

预期： PASS。

---

### 任务 3: 新增应用删除 API，并调整应用列表操作列

**文件：**
- 修改： `src/easyauth/admin_console/apps_api.py`
- 修改： `src/easyauth/admin_console/urls.py`
- 修改： `tests/integration/admin_console/test_apps_api_ops1.py`
- 修改： `frontend/src/pages/console/ConsoleAppList.tsx`
- 修改： `frontend/src/pages/console/ConsoleAppList.test.tsx`

- [ ] **步骤 1: 写后端删除测试**

在 `test_apps_api_ops1.py` 增加 superuser 删除测试：

```python
def test_ops1_apps_api_superuser_deletes_app_and_records_audit() -> None:
    client = _logged_in_superuser("ops1-app-delete-admin")
    app = App.objects.create(app_key="ops1-api-delete", name="Delete Me")
    app_id = app.id

    response = client.delete(f"{APPS_API_URL}/{app.app_key}")

    assert response.status_code == HTTPStatus.NO_CONTENT
    assert App.objects.filter(id=app_id).exists() is False
    assert AuditLog.objects.filter(
        actor_id="ops1-app-delete-admin",
        event_type="console_app_deleted",
        target_id=str(app_id),
        metadata__app_key="ops1-api-delete",
    ).exists()
```

再增加非 superuser 拒绝测试：

```python
def test_ops1_apps_api_non_superuser_cannot_delete_app() -> None:
    client = _logged_in_user("ops1-app-delete-owner")
    app = App.objects.create(app_key="ops1-api-delete-denied", name="Delete Denied")
    _ = AppMembership.objects.create(app=app, user_id="ops1-app-delete-owner", role="owner")

    response = client.delete(f"{APPS_API_URL}/{app.app_key}")

    app.refresh_from_db()
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"]["code"] == ErrorCode.PERMISSION_DENIED
    assert app.app_key == "ops1-api-delete-denied"
```

- [ ] **步骤 2: 实现 `DELETE /console/api/v1/apps/<app_key>`**

在 `console_app_detail` 中分派 `DELETE`：

```python
def console_app_detail(request: HttpRequest, app_key: str) -> JsonResponse:
    if request.method == "PATCH":
        return _patch_app(request, app_key)
    if request.method == "DELETE":
        return _delete_app(request, app_key)
    if request.method != "GET":
        return _method_not_allowed()
    ...
```

新增 `_delete_app`，仅 superuser 可执行，删除前记录 `app_key`、`name`、`is_active`。实现时需要从 `django.http` 引入 `HttpResponse`，并把相关 view 返回类型放宽为 `JsonResponse | HttpResponse`：

```python
def _delete_app(request: HttpRequest, app_key: str) -> JsonResponse | HttpResponse:
    match require_console_actor(request):
        case ConsoleActor() as actor:
            pass
        case JsonResponse() as response:
            return response

    if not actor.is_superuser:
        return _error_response(
            ErrorCode.PERMISSION_DENIED,
            "只有系统管理员可以删除应用。",
            status=HTTPStatus.FORBIDDEN,
        )

    match _visible_app(actor, app_key):
        case App() as app:
            pass
        case JsonResponse() as response:
            return response

    metadata: dict[str, JsonValue] = {
        "app_key": app.app_key,
        "name": app.name,
        "is_active": app.is_active,
    }
    app_id = app.id
    with transaction.atomic():
        _record_app_event(app, actor, "console_app_deleted", metadata)
        app.delete()
    return HttpResponse(status=HTTPStatus.NO_CONTENT)
```

- [ ] **步骤 3: 前端列表加入启用/停用/删除**

在 `ConsoleAppList.tsx` 增加两个 mutation：

```ts
const updateStatusMutation = useMutation({
  mutationFn: ({ appKey, isActive }: { appKey: string; isActive: boolean }) =>
    apiRequest(`/console/api/v1/apps/${appKey}`, {
      method: "PATCH",
      body: { is_active: isActive },
    }),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["console", "apps"] }),
});

const deleteMutation = useMutation({
  mutationFn: (appKey: string) =>
    apiRequest(`/console/api/v1/apps/${appKey}`, {
      method: "DELETE",
    }),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["console", "apps"] }),
});
```

操作列 header 改为 `操作`，cell 使用任务 4 新增的 `TableActionCell` / `TableRowActionButton`。管理员显示启停和删除；非管理员只显示进入。

- [ ] **步骤 4: 删除创建弹窗中的启用勾选**

移除 `CreateAppDialog` 的 `isActive` state、`Field label="启用应用"` 和提交 payload 中的 `is_active`。后端默认 `is_active=True` 保持不变。

- [ ] **步骤 5: 运行应用 API 与列表测试**

运行：

```bash
uv run pytest tests/integration/admin_console/test_apps_api_ops1.py -q
pnpm --dir frontend test frontend/src/pages/console/ConsoleAppList.test.tsx
```

预期： PASS。

---

### 任务 4: 引入 EasyTrade 风格的表格操作按钮 primitive 并批量替换

**文件：**
- 修改： `frontend/src/components/Button.tsx`
- 新增： `frontend/src/components/ui/TableActions.tsx`
- 修改： `frontend/src/pages/console/ConsoleAppList.tsx`
- 修改： `frontend/src/pages/console/workspace/tabs/CatalogTab.tsx`
- 修改： `frontend/src/pages/console/workspace/tabs/MatrixTab.tsx`
- 修改： `frontend/src/pages/console/workspace/tabs/OverviewTab.tsx`
- 修改： `frontend/src/pages/console/workspace/tabs/RulesTab.tsx`
- 修改： `frontend/src/pages/console/workspace/tabs/CredentialsTab.tsx`
- 修改： `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`

- [ ] **步骤 1: 增强 Button 支持链接式行内动作**

保持现有 `Button` API，新增 `asChild` 不必要；本项目可先提供普通 button 和 link 两个 action primitive，避免引入 Radix Slot。

- [ ] **步骤 2: 新增 `TableActions.tsx`**

新增文件内容：

```tsx
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { Button } from "../Button";

type TableActionTone = "normal" | "danger";

export function TableActionCell({
  children,
  align = "end",
  wrap = false,
}: {
  children: ReactNode;
  align?: "start" | "end";
  wrap?: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-1.5 ${align === "end" ? "justify-end" : "justify-start"} ${
        wrap ? "flex-wrap" : "flex-nowrap whitespace-nowrap"
      }`}
      onClick={(event) => event.stopPropagation()}
    >
      {children}
    </div>
  );
}

export function TableRowActionButton({
  tone = "normal",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: TableActionTone }) {
  return <Button {...props} size="sm" variant={tone === "danger" ? "ghost-danger" : "ghost"} />;
}

export function TableRowActionLink({ className = "", ...props }: LinkProps) {
  return (
    <Link
      {...props}
      className={`inline-flex h-7 shrink-0 items-center justify-center gap-1.5 rounded-[2px] border border-transparent bg-transparent px-2.5 text-[12px] font-medium tracking-wide text-ink-soft transition-all duration-150 hover:bg-ink/[0.04] hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--amber)_/_0.5)] active:[transform:translateY(1px)] ${className}`}
    />
  );
}
```

- [ ] **步骤 3: 替换所有 console 表格操作按钮**

统一规则：

- `编辑`、`进入`、`启用` 使用 normal。
- `停用`、`删除`、`移除`、`禁用` 使用 danger。
- 操作列 header 均为 `操作`。
- 操作列 cell 外层均为 `TableActionCell`。

- [ ] **步骤 4: 更新测试中按钮查询**

如果同一行有多个操作按钮，测试必须使用 `within(row).getByRole(...)`，不要全局查询同名按钮。

- [ ] **步骤 5: 运行 console 工作台测试**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/console/ConsoleAppWorkspace.test.tsx
pnpm --dir frontend typecheck
```

预期： PASS。

---

### 任务 5: 应用工作台 tab 指示器加入动画

**文件：**
- 修改： `frontend/src/pages/console/ConsoleAppWorkspace.tsx`
- 修改： `frontend/src/pages/console/ConsoleAppWorkspace.test.tsx`

- [ ] **步骤 1: 保留 URL search param 作为 tab 状态源**

不改变 `?tab=` 语义，只改指示器表现。

- [ ] **步骤 2: 使用绝对定位指示器替代每个按钮的激活下边框**

将 tab 容器设为 `relative`，按钮使用 refs 或 CSS grid 变量计算 active 指示器。保守实现可先用 CSS 变量：

```tsx
<div
  className="relative mb-6 flex gap-1 overflow-x-auto border-b border-[rgb(var(--hairline))]"
  style={{ "--active-tab-index": activeTabIndex, "--tab-count": TABS.length } as React.CSSProperties}
>
  <span
    className="pointer-events-none absolute bottom-0 left-0 h-0.5 bg-amber-ink transition-transform duration-200 ease-out"
    style={{ width: "calc(100% / var(--tab-count))", transform: "translateX(calc(var(--active-tab-index) * 100%))" }}
  />
  ...
</div>
```

如果横向滚动下每个 tab 宽度不等，则改用 `useRef` 读取 active button 的 `offsetLeft` 和 `offsetWidth`，设置 `indicatorStyle`，保证指示器跟随真实按钮宽度。

- [ ] **步骤 3: 测试 tab 切换仍更新内容与 URL**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/console/ConsoleAppWorkspace.test.tsx
```

预期： PASS。

---

### 任务 6: 运营页非管理员不发请求，失败图标无外框

**文件：**
- 修改： `frontend/src/pages/console/OperationsPage.tsx`
- 新增： `frontend/src/pages/console/OperationsPage.test.tsx`
- 修改： `frontend/src/components/ui/PageState.tsx`

- [ ] **步骤 1: 写前端测试，证明非管理员不请求运营 API**

新增 `OperationsPage.test.tsx`：

```tsx
test("非系统管理员打开运营页时不请求运营 API", async () => {
  document.body.dataset.currentUserRole = "研发中心";
  const fetchMock = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetchMock);

  renderOperationsPage("/console/operations/access-requests");

  expect(await screen.findByText("只有系统管理员可以执行该操作。")).toBeVisible();
  expect(fetchMock).not.toHaveBeenCalled();
});
```

- [ ] **步骤 2: OperationsPage 前置判断角色**

复用本地 `isConsoleAdmin()`：

```tsx
const isAdmin = isConsoleAdmin();
const query = useQuery({
  queryKey: ["console", "operations", section],
  queryFn: () => apiRequest<{ items?: OperationRow[]; data?: OperationRow[] }>(config.endpoint),
  enabled: isAdmin,
});

if (!isAdmin) {
  return (
    <>
      <PageHeader eyebrow="Operations" title={config.title} description="系统管理员的授权运营和依赖观测入口。" />
      <PageState tone="signal" title="运营数据加载失败" description="只有系统管理员可以执行该操作。" />
    </>
  );
}
```

- [ ] **步骤 3: PageState 支持无图标外框**

给 `PageState` 增加 `iconFrame?: boolean`，默认 `true`；运营页传 `iconFrame={false}`：

```tsx
{iconFrame ? (
  <div className={`mb-4 flex size-10 items-center justify-center rounded-[2px] bg-paper-deep ${TONE_CLASSES[tone]}`}>
    <Icon size={20} />
  </div>
) : (
  <Icon size={24} className={`mb-4 ${TONE_CLASSES[tone]}`} />
)}
```

- [ ] **步骤 4: 运行运营页测试**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/console/OperationsPage.test.tsx
pnpm --dir frontend typecheck
```

预期： PASS。

---

### 任务 7: 全量验证与运行中页面验证

**文件：**
- 除非验证发现问题，否则无需改代码。

- [ ] **步骤 1: 后端相关测试**

运行：

```bash
uv run pytest tests/integration/portal/test_request_catalog_api.py tests/integration/admin_console/test_apps_api_ops1.py tests/integration/admin_console/test_operations_api_ops3.py -q
```

预期： PASS。

- [ ] **步骤 2: 前端相关测试**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx frontend/src/pages/console/ConsoleAppList.test.tsx frontend/src/pages/console/ConsoleAppWorkspace.test.tsx frontend/src/pages/console/OperationsPage.test.tsx
pnpm --dir frontend typecheck
```

预期： PASS。

- [ ] **步骤 3: 构建**

运行：

```bash
pnpm --dir frontend build
```

预期： PASS，生成最新 Vite build 产物。

- [ ] **步骤 4: 重启 Django 开发服务**

因为修改了 Django 后端、React build 产物会影响运行中页面响应，必须重启当前 Django 开发服务。按当前终端实际启动方式重启；如果没有运行中的服务，启动：

```bash
uv run python manage.py runserver 127.0.0.1:8000
```

预期： 服务监听 `127.0.0.1:8000`。

- [ ] **步骤 5: 用真实 HTTP 或浏览器验证新代码已加载**

运行：

```bash
curl -sS http://127.0.0.1:8000/portal/request | rg "easyauth-root|申请权限"
curl -sS http://127.0.0.1:8000/console/operations/access-requests | rg "easyauth-root|Operations"
```

预期： 两个页面都返回 React shell。

- [ ] **步骤 6: 浏览器冒烟**

运行：

```bash
pnpm --dir frontend e2e -- frontend/e2e/smoke.spec.ts
```

预期： PASS。重点看 `/portal/request`、`/console`、`/console/apps/demo`、`/console/operations/access-requests`。

---

## 执行拆分建议

- 子代理 A：任务 1，portal 目录后端口径和集成测试。
- 子代理 B：任务 2，portal 文案和布局。
- 子代理 C：任务 3，console 应用删除 API 与应用列表操作。
- 子代理 D：任务 4，表格 action primitive 与各 console 表格按钮替换。
- 子代理 E：任务 5 和任务 6，tab 动画与运营页权限态。
- 主代理：审阅、冲突整合、运行全量验证、重启开发服务并做真实页面验证。

## 明确不做

- 不让 portal 直接调用 console API。
- 不用前端 mock 数据填补后端目录问题。
- 不增加“无权限时先请求再展示错误”的 fallback。
- 不保留创建应用时的内部启用勾选。
- 不做软删除兼容层；删除按钮必须对应真实 `DELETE` 语义。
