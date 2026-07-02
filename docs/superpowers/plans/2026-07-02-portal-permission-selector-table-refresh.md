# 门户权限选择表格重构实施计划

> **给 agentic workers:** REQUIRED SUB-SKILL: 使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实施本计划。步骤使用 checkbox（`- [ ]`）语法跟踪。

**目标:** 按设计规格把门户“申请权限”的权限选择表格重构为审计控制台式权限篮，保留 TanStack Table 原始构建、原生表格语义和现有提交契约。

**架构:** `PermissionSelector` 继续是页面内局部组件，直接使用 `useReactTable`、row model、`flexRender` 和原生 `<table>`。新增“仅看已选”只作为 `PermissionSelector` 内部展示状态，过滤后 rows 再交给 TanStack pagination，保证表格、工具条和分页口径同源。不新增通用表格包装层、不引入兼容层、不改变后端 API 或提交 payload。

**技术栈:** React 19、TypeScript、TanStack Table v8、Tailwind CSS 4、Vitest、Testing Library、Django 5.2。

---

## 设计来源

- 规格文档：`docs/superpowers/specs/2026-07-02-portal-permission-selector-table-design.md`
- 主要实现文件：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 专属样式文件：`frontend/src/styles/features/permission-selector.css`
- 行为测试：`frontend/src/pages/portal/PortalPage.test.tsx`
- 架构测试：`frontend/src/components/tableArchitecture.test.ts`

## 关键口径

- `当前显示 X/Y` 使用当前已生成 rows 的展示口径，不临时展开未展开分支。
- 未开启“仅看已选”时，`X` 与 `Y` 都等于当前 rows 数量。
- 开启“仅看已选”时，`X` 等于过滤后 rows 数量，`Y` 等于过滤前当前 rows 数量。
- 如果权限组折叠但内部已有已选权限，过滤态只显示命中的权限组行；用户展开后才显示命中的子权限行。
- `已选 N 项` 直接使用 `selectedKeys.length`，保持与外层 hint 和提交口径一致。
- `scope 已设置 N 项` 使用 `Object.values(selectedScopes).filter(Boolean).length`，不推导静默默认值。
- “仅看已选”不改变 `selectedKeys`、`selectedScopes`、`expandedGroupKeys`、提交 payload 或后端数据。
- 多 scope 权限的选择入口仍在 `scope` 列 checkbox；选择列显示非交互说明“按 scope 选择”。
- `rows.length === 0` 不再返回 `null`，而是在“直接权限”区域展示明确空状态。

## 文件结构

- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
  - 负责 TanStack Table 数据、列定义、工具条、本地过滤、分页、权限组/权限项单元格。
- 修改：`frontend/src/styles/features/permission-selector.css`
  - 负责权限表格专属工具条、树形轨道、已选态、scope chip、过滤空态和动画样式。
- 修改：`frontend/src/pages/portal/PortalPage.test.tsx`
  - 覆盖表头语义、展开 `aria-expanded`、事件冒泡边界、多 scope 语义、工具条、过滤、分页和空状态。
- 修改：`frontend/src/components/tableArchitecture.test.ts`
  - 强化 TanStack 原始构建和旧表格包装禁止规则。

---

### 任务 1: 增加门户权限选择行为测试

**文件：**
- 修改：`frontend/src/pages/portal/PortalPage.test.tsx`

- [ ] **步骤 1: 增加测试 fixture**

在 `jsonResponse` 前加入以下测试数据与 fetch helper：

```ts
const portalPermissionSelectorCatalog = {
  apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] }],
  approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
  authorization_groups: [],
  permission_groups: [
    {
      id: 1,
      app_key: "crm",
      type: "group",
      key: "orders",
      name: "订单",
      permissions: [
        { id: 101, app_key: "crm", key: "orders.read", name: "查看订单", scopes: [{ key: "SELF", name: "本人" }] },
        { id: 102, app_key: "crm", key: "orders.export", name: "导出订单", scopes: [{ key: "SELF", name: "本人" }] },
      ],
      children: [
        {
          id: 2,
          app_key: "crm",
          type: "group",
          key: "orders.refund",
          name: "退款",
          permissions: [
            {
              id: 103,
              app_key: "crm",
              key: "orders.refund.approve",
              name: "审批退款",
              scopes: [
                { key: "SELF", name: "本人" },
                { key: "TEAM", name: "团队" },
              ],
            },
          ],
        },
      ],
    },
  ],
  ungrouped_permissions: [{ id: 104, app_key: "crm", key: "dashboard.view", name: "查看看板", scopes: [{ key: "GLOBAL", name: "全局" }] }],
};

const emptyDirectPermissionCatalog = {
  apps: [{ id: 1, app_key: "crm", name: "CRM" }],
  approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
  authorization_groups: [],
  permission_groups: [],
  ungrouped_permissions: [],
};

function permissionSelectorFetchMock(payload: unknown) {
  return vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url === "/portal/api/v1/request-catalog") {
      return jsonResponse(payload);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}
```

- [ ] **步骤 2: 写表头、展开 aria 和 checkbox 冒泡测试**

在 `describe("PortalPage access request form", () => {` 内追加测试：

```ts
  test("权限选择表格保留表头语义、展开状态和 checkbox 冒泡边界", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      expect(within(permissionTable).getByRole("columnheader", { name: "权限" })).toBeVisible();
      expect(within(permissionTable).getByRole("columnheader", { name: "权限 key" })).toBeVisible();
      expect(within(permissionTable).getByRole("columnheader", { name: "scope" })).toBeVisible();
      expect(within(permissionTable).getByRole("columnheader", { name: "选择" })).toBeVisible();

      const expandButton = within(permissionTable).getByRole("button", { name: "展开 订单" });
      expect(expandButton).toHaveAttribute("aria-expanded", "false");
      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();

      const groupCheckbox = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders" });
      await user.click(groupCheckbox);
      expect(groupCheckbox).toBeChecked();
      expect(within(permissionTable).getByRole("button", { name: "展开 订单" })).toHaveAttribute("aria-expanded", "false");
      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      expect(within(permissionTable).getByRole("button", { name: "收起 订单" })).toHaveAttribute("aria-expanded", "true");
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();

      await user.click(within(permissionTable).getByRole("button", { name: "收起 订单" }));
      expect(within(permissionTable).getByRole("button", { name: "展开 订单" })).toHaveAttribute("aria-expanded", "false");
    } finally {
      vi.unstubAllGlobals();
    }
  });
```

- [ ] **步骤 3: 写多 scope 选择列语义测试**

继续追加测试：

```ts
  test("多 scope 权限选择列显示按 scope 选择语义", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 退款" }));

      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve SELF" })).toBeVisible();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve TEAM" })).toBeVisible();
      const selectionHint = within(permissionTable).getByLabelText("orders.refund.approve 多 scope 选择");
      expect(selectionHint).toHaveTextContent("按 scope 选择");
      expect(selectionHint).not.toHaveTextContent("-");
    } finally {
      vi.unstubAllGlobals();
    }
  });
```

- [ ] **步骤 4: 写工具条和仅看已选过滤测试**

继续追加测试：

```ts
  test("权限选择工具条展示状态并支持仅看已选过滤", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      expect(screen.getByText("已选 0 项")).toBeVisible();
      expect(screen.getByText("scope 已设置 3 项")).toBeVisible();
      expect(screen.getByText("当前显示 2/2")).toBeVisible();

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      expect(screen.getByText("当前显示 5/5")).toBeVisible();

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export" }));
      expect(screen.getByText("已选 1 项")).toBeVisible();

      await user.click(screen.getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("订单")).toBeVisible();
      expect(within(permissionTable).getByText("导出订单")).toBeVisible();
      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();
      expect(within(permissionTable).queryByText("查看看板")).not.toBeInTheDocument();
      expect(screen.getByText("当前显示 2/5")).toBeVisible();
      expect(screen.getByText("第 1-2 条 / 共 2 条")).toBeVisible();

      await user.click(screen.getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(within(permissionTable).getByText("查看看板")).toBeVisible();
      expect(screen.getByText("当前显示 5/5")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });
```

- [ ] **步骤 5: 写过滤空状态和无直接权限空状态测试**

继续追加测试：

```ts
  test("仅看已选无结果时显示表格内空状态", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(screen.getByRole("switch", { name: "仅看已选" }));
      expect(permissionTable).toBeVisible();
      expect(within(permissionTable).getByText("当前没有已选直接权限")).toBeVisible();
      expect(screen.getByText("当前显示 0/2")).toBeVisible();

      await user.click(screen.getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("订单")).toBeVisible();
      expect(within(permissionTable).getByText("查看看板")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("应用存在但没有直接权限时直接权限区域显示空状态", async () => {
    const fetchMock = permissionSelectorFetchMock(emptyDirectPermissionCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      expect(await screen.findByRole("status")).toHaveTextContent("当前应用没有可直接申请的权限，可仅按权限组发起申请。");
      expect(screen.getByText("当前应用未返回可直接申请的权限，可仅选择权限组发起申请。")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });
```

- [ ] **步骤 6: 运行新测试，确认红灯**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx
```

预期：新增测试失败，失败点包括找不到“仅看已选”、工具条统计、多 scope 文案或空状态。不要提交红灯测试。

---

### 任务 2: 实现工具条、过滤数据流和空状态

**文件：**
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 修改：`frontend/src/pages/portal/PortalPage.test.tsx`

- [ ] **步骤 1: 扩展 permission row 类型**

在 `PermissionSelectorRow` 的 `permission` 分支增加 `isSelected`：

```ts
  | {
      type: "permission";
      id: string;
      permission: ScopedPermissionItem;
      depth: number;
      isSelected: boolean;
      isExiting: boolean;
    };
```

- [ ] **步骤 2: 在 `PermissionSelector` 中新增过滤状态、统计和过滤后 rows**

在 `rows` `useMemo` 后加入：

```tsx
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const displayRows = useMemo(
    () => (showSelectedOnly ? filterRowsToSelected(rows) : rows),
    [rows, showSelectedOnly],
  );
  const toolbarStats = useMemo(
    () => buildPermissionSelectorToolbarStats(rows, displayRows, selectedKeys, selectedScopes),
    [displayRows, rows, selectedKeys, selectedScopes],
  );
```

- [ ] **步骤 3: 让 TanStack Table 使用过滤后 rows**

把 `useReactTable` 的 `data` 从 `rows` 改为 `displayRows`：

```tsx
  const table = useReactTable({
    data: displayRows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (row) => row.id,
  });
```

- [ ] **步骤 4: 切换“仅看已选”时回到第一页**

在 `table` 创建后加入：

```tsx
  useEffect(() => {
    table.setPageIndex(0);
  }, [showSelectedOnly, table]);
```

如果执行时发现 `table` 依赖触发不必要重渲染，改为带 ref 的版本：

```tsx
  const previousShowSelectedOnly = useRef(showSelectedOnly);
  useEffect(() => {
    if (previousShowSelectedOnly.current !== showSelectedOnly) {
      previousShowSelectedOnly.current = showSelectedOnly;
      table.setPageIndex(0);
    }
  }, [showSelectedOnly, table]);
```

- [ ] **步骤 5: 修正无直接权限空状态**

把当前分支：

```tsx
  if (rows.length === 0) {
    return null;
  }
```

替换为：

```tsx
  if (rows.length === 0) {
    return (
      <div className="permission-selector__surface">
        <EmptyState title="暂无可选直接权限" description="当前应用未返回可直接申请的权限，可仅选择权限组发起申请。" />
      </div>
    );
  }
```

同时把 `PortalPage.test.tsx` 中旧测试 `未选择权限组或直接权限时不能提交申请` 的断言从：

```ts
      expect(screen.queryByText("暂无可选直接权限")).not.toBeInTheDocument();
```

改为：

```ts
      expect(screen.getByText("当前应用未返回可直接申请的权限，可仅选择权限组发起申请。")).toBeVisible();
```

- [ ] **步骤 6: 插入顶部工具条**

在返回 JSX 的 `<div className="paper-card ...">` 里面、`<div className="overflow-x-auto">` 前插入：

```tsx
      <PermissionSelectorToolbar
        selectedCount={toolbarStats.selectedCount}
        configuredScopeCount={toolbarStats.configuredScopeCount}
        visibleCount={toolbarStats.visibleCount}
        totalCount={toolbarStats.totalCount}
        showSelectedOnly={showSelectedOnly}
        onShowSelectedOnlyChange={setShowSelectedOnly}
      />
```

- [ ] **步骤 7: 新增工具条局部组件**

在 `PermissionSelector` 后、`PermissionGroupNameCell` 前加入：

```tsx
function PermissionSelectorToolbar({
  selectedCount,
  configuredScopeCount,
  visibleCount,
  totalCount,
  showSelectedOnly,
  onShowSelectedOnlyChange,
}: {
  selectedCount: number;
  configuredScopeCount: number;
  visibleCount: number;
  totalCount: number;
  showSelectedOnly: boolean;
  onShowSelectedOnlyChange: (showSelectedOnly: boolean) => void;
}) {
  return (
    <div className="permission-selector__toolbar">
      <div className="permission-selector__toolbar-stats" aria-label="权限选择状态">
        <span className="permission-selector__toolbar-stat">已选 {selectedCount} 项</span>
        <span className="permission-selector__toolbar-stat">scope 已设置 {configuredScopeCount} 项</span>
        <span className="permission-selector__toolbar-stat">当前显示 {visibleCount}/{totalCount}</span>
      </div>
      <label className="permission-selector__toolbar-toggle">
        <input
          type="checkbox"
          role="switch"
          aria-label="仅看已选"
          checked={showSelectedOnly}
          onChange={(event) => onShowSelectedOnlyChange(event.currentTarget.checked)}
        />
        <span aria-hidden="true" className="permission-selector__toolbar-toggle-track">
          <span className="permission-selector__toolbar-toggle-thumb" />
        </span>
        <span>仅看已选</span>
      </label>
    </div>
  );
}
```

- [ ] **步骤 8: 修正表格内过滤空状态**

把 `visibleRows.length === 0` 的 EmptyState 改为根据 `showSelectedOnly` 分支：

```tsx
                  <EmptyState
                    title={showSelectedOnly ? "当前没有已选直接权限" : "暂无可选直接权限"}
                    description={
                      showSelectedOnly
                        ? "关闭仅看已选后可继续浏览并选择权限。"
                        : "当前应用未返回可直接申请的权限，可仅选择权限组发起申请。"
                    }
                  />
```

- [ ] **步骤 9: 新增过滤和统计 helper**

在 `buildPermissionRows` 前加入：

```ts
interface PermissionSelectorToolbarStats {
  selectedCount: number;
  configuredScopeCount: number;
  visibleCount: number;
  totalCount: number;
}

function buildPermissionSelectorToolbarStats(
  rows: PermissionSelectorRow[],
  displayRows: PermissionSelectorRow[],
  selectedKeys: string[],
  selectedScopes: Record<string, string>,
): PermissionSelectorToolbarStats {
  return {
    selectedCount: selectedKeys.length,
    configuredScopeCount: countConfiguredScopes(selectedScopes),
    visibleCount: displayRows.length,
    totalCount: rows.length,
  };
}

function countConfiguredScopes(selectedScopes: Record<string, string>): number {
  return Object.values(selectedScopes).filter(Boolean).length;
}

function filterRowsToSelected(rows: PermissionSelectorRow[]): PermissionSelectorRow[] {
  return rows.filter((row) => rowMatchesSelected(row));
}

function rowMatchesSelected(row: PermissionSelectorRow): boolean {
  if (row.type === "group") {
    return row.selectionState !== "unchecked";
  }
  return row.isSelected;
}
```

- [ ] **步骤 10: 给 permission rows 写入 `isSelected`**

在 `buildPermissionRows` 的 `ungroupedPermissions.map` 中加入：

```ts
      isSelected: isPermissionSelected(permission.key, selectedKeys),
```

完整片段：

```ts
    ...ungroupedPermissions.map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: 0,
      isSelected: isPermissionSelected(permission.key, selectedKeys),
      isExiting: false,
    })),
```

在 `buildGroupRows` 的 `group.permissions.map` 中加入：

```ts
      isSelected: isPermissionSelected(permission.key, selectedKeys),
```

完整片段：

```ts
    ...(group.permissions ?? []).map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: depth + 1,
      isSelected: isPermissionSelected(permission.key, selectedKeys),
      isExiting: isChildExiting,
    })),
```

- [ ] **步骤 11: 运行任务测试，确认绿灯**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx
```

预期：`PortalPage.test.tsx` 全部通过。

- [ ] **步骤 12: 提交任务 1 和任务 2 的红绿结果**

提交测试与数据流实现：

```bash
git add frontend/src/pages/portal/PortalPage.test.tsx frontend/src/pages/portal/components/PermissionSelector.tsx
git commit -m "feat: add portal permission selector selected filter"
```

---

### 任务 3: 重构权限表格视觉与单元格表达

**文件：**
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 修改：`frontend/src/styles/features/permission-selector.css`

- [ ] **步骤 1: 给行添加已选态 class**

在渲染 `<tr>` 的 `className` 中加入：

```tsx
                    row.original.type === "group" && row.original.selectionState !== "unchecked" && "permission-selector__row--group-selected",
                    row.original.type === "permission" && row.original.isSelected && "permission-selector__row--selected",
```

完整位置应在现有：

```tsx
                    row.original.type === "group" && "permission-selector__row--group bg-paper-deep/60 hover:bg-paper-deep",
                    row.original.isExiting && "permission-selector__row--exiting",
```

附近。

- [ ] **步骤 2: 调整权限组名称单元格**

把 `PermissionGroupNameCell` 的 button 内容改为：

```tsx
    <button
      type="button"
      className="permission-selector__group-button"
      onClick={(event) => {
        event.stopPropagation();
        onToggleGroup(group.key);
      }}
      aria-expanded={isExpanded}
      aria-label={`${isExpanded ? "收起" : "展开"} ${group.name}`}
      style={depthStyle(depth)}
    >
      <span className="permission-selector__tree-rail" aria-hidden="true" />
      <ChevronRight size={16} className={isExpanded ? "permission-selector__chevron permission-selector__chevron--expanded" : "permission-selector__chevron"} />
      <span className="permission-selector__group-name">{group.name}</span>
      <span className={selectedCount > 0 ? "permission-selector__group-count permission-selector__group-count--active" : "permission-selector__group-count"}>
        {selectedCount}/{permissionCount}
      </span>
    </button>
```

- [ ] **步骤 3: 调整权限项名称单元格**

在 columns 的 permission cell 中，把 permission 分支改为：

```tsx
            <span className="permission-selector__permission-name" style={depthStyle(row.original.depth)}>
              <span className="permission-selector__leaf-marker" aria-hidden="true" />
              <span className="permission-selector__permission-label">{row.original.permission.name}</span>
            </span>
```

- [ ] **步骤 4: 调整批量 scope select 表达**

在 `PermissionGroupScopeCell` 中给 `SelectInput` 增加 className，并改默认选项：

```tsx
    <SelectInput
      className="permission-selector__scope-bulk-select"
      value=""
      onClick={(event) => event.stopPropagation()}
      onChange={(event) => onScopeChange(group, event.currentTarget.value)}
      aria-label={`${group.key} 权限组 scope`}
    >
      <option value="">批量应用 scope</option>
      {scopeOptions.map((scopeKey) => (
        <option key={scopeKey} value={scopeKey}>
          应用 {scopeKey}
        </option>
      ))}
    </SelectInput>
```

- [ ] **步骤 5: 调整多 scope chip 样式**

在 `PermissionScopeCell` 的多 scope 分支中，把容器和 label class 改为：

```tsx
        <div className="permission-selector__scope-chip-list">
          {scopes.map((scope) => (
            <label key={scope.key} className="permission-selector__scope-chip">
              <input
                type="checkbox"
                checked={selectedKeys.includes(directGrantSelectionKey(permission.key, scope.key))}
                onClick={(event) => event.stopPropagation()}
                onChange={() => onToggle(directGrantSelectionKey(permission.key, scope.key))}
                aria-label={`选择 ${permission.key} ${scope.key}`}
              />
              <span>
                {scope.name} ({scope.key})
              </span>
            </label>
          ))}
        </div>
```

- [ ] **步骤 6: 调整多 scope 选择列提示**

在 `PermissionSelectionCell` 中，把多 scope 分支从 `-` 改为：

```tsx
        <span className="permission-selector__selection-hint" aria-label={`${permission.key} 多 scope 选择`}>
          按 scope 选择
        </span>
```

- [ ] **步骤 7: 替换权限选择专属 CSS**

将 `frontend/src/styles/features/permission-selector.css` 更新为以下内容：

```css
.permission-selector__surface {
  overflow: hidden;
  border: 1px solid rgb(var(--hairline));
  border-radius: 6px;
  background: rgb(var(--paper));
  box-shadow: 0 12px 28px rgb(15 23 42 / 0.06);
}

.permission-selector__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid rgb(var(--hairline-soft));
  background: linear-gradient(180deg, rgb(var(--paper-deep) / 0.76), rgb(var(--paper) / 0.96));
  padding: 0.75rem;
}

.permission-selector__toolbar-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.permission-selector__toolbar-stat {
  display: inline-flex;
  align-items: center;
  min-height: 1.75rem;
  border: 1px solid rgb(var(--hairline));
  border-radius: 999px;
  background: rgb(var(--paper));
  padding: 0.25rem 0.65rem;
  color: rgb(var(--ink-soft));
  font-size: 12px;
  font-weight: 600;
}

.permission-selector__toolbar-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: rgb(var(--ink-soft));
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
  user-select: none;
}

.permission-selector__toolbar-toggle input {
  position: absolute;
  inline-size: 1px;
  block-size: 1px;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  overflow: hidden;
  white-space: nowrap;
}

.permission-selector__toolbar-toggle-track {
  display: inline-flex;
  align-items: center;
  width: 2.25rem;
  height: 1.25rem;
  border: 1px solid rgb(var(--hairline-strong));
  border-radius: 999px;
  background: rgb(var(--paper));
  padding: 0.125rem;
  transition: border-color 160ms var(--ease-press), background 160ms var(--ease-press);
}

.permission-selector__toolbar-toggle-thumb {
  width: 0.875rem;
  height: 0.875rem;
  border-radius: 999px;
  background: rgb(var(--ink-faint));
  transition: transform 160ms var(--ease-press), background 160ms var(--ease-press);
}

.permission-selector__toolbar-toggle input:checked + .permission-selector__toolbar-toggle-track {
  border-color: rgb(var(--amber));
  background: rgb(var(--amber) / 0.12);
}

.permission-selector__toolbar-toggle input:checked + .permission-selector__toolbar-toggle-track .permission-selector__toolbar-toggle-thumb {
  background: rgb(var(--amber));
  transform: translateX(1rem);
}

.permission-selector__toolbar-toggle input:focus-visible + .permission-selector__toolbar-toggle-track {
  outline: 2px solid rgb(var(--amber) / 0.5);
  outline-offset: 2px;
}

.permission-selector__row {
  --permission-depth: 0;
  position: relative;
}

.permission-selector__row:not(.permission-selector__row--group) {
  animation: permissionSelectorRowEnter 160ms var(--ease-out-paper) both;
}

.permission-selector__row--group {
  cursor: pointer;
}

.permission-selector__row--selected {
  background: rgb(var(--amber) / 0.055);
}

.permission-selector__row--selected > td:first-child,
.permission-selector__row--group-selected > td:first-child {
  box-shadow: inset 3px 0 0 rgb(var(--amber));
}

.permission-selector__row--group-selected {
  background: rgb(var(--amber) / 0.075);
}

.permission-selector__row--exiting {
  pointer-events: none;
  animation: permissionSelectorRowExit 160ms var(--ease-press) both;
}

.permission-selector__group-button,
.permission-selector__permission-name {
  margin-left: calc(var(--permission-depth, 0) * 1.25rem);
}

.permission-selector__group-button {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
  border-radius: 4px;
  padding: 0.25rem 0.35rem;
  color: rgb(var(--ink));
  font-size: 13px;
  font-weight: 700;
  text-align: left;
  transition: background 160ms var(--ease-press), color 160ms var(--ease-press);
}

.permission-selector__group-button:hover {
  background: rgb(var(--ink) / 0.05);
}

.permission-selector__tree-rail {
  width: 3px;
  height: 1.5rem;
  border-radius: 999px;
  background: rgb(var(--amber) / 0.35);
}

.permission-selector__chevron {
  flex: 0 0 auto;
  color: rgb(var(--ink-soft));
  transition: transform 160ms var(--ease-press);
}

.permission-selector__chevron--expanded {
  transform: rotate(90deg);
}

.permission-selector__group-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-selector__group-count {
  border-radius: 999px;
  background: rgb(var(--paper-deep));
  padding: 0.125rem 0.45rem;
  color: rgb(var(--ink-soft));
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 700;
  line-height: 1rem;
}

.permission-selector__group-count--active {
  background: rgb(var(--amber) / 0.12);
  color: rgb(var(--amber));
}

.permission-selector__permission-name {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  color: rgb(var(--ink));
  font-size: 13px;
  font-weight: 600;
}

.permission-selector__permission-name::before {
  position: absolute;
  top: -0.75rem;
  bottom: -0.75rem;
  left: -0.7rem;
  width: 1px;
  background: rgb(var(--hairline-strong));
  content: "";
}

.permission-selector__leaf-marker {
  width: 0.45rem;
  height: 0.45rem;
  flex: 0 0 auto;
  border: 1px solid rgb(var(--amber) / 0.45);
  border-radius: 999px;
  background: rgb(var(--paper));
}

.permission-selector__permission-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-selector__scope-bulk-select {
  min-width: 8rem;
  font-weight: 600;
}

.permission-selector__scope-chip-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.permission-selector__scope-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  border: 1px solid rgb(var(--hairline-strong));
  border-radius: 999px;
  background: rgb(var(--paper));
  padding: 0.35rem 0.65rem;
  color: rgb(var(--ink-soft));
  font-size: 12px;
  font-weight: 600;
}

.permission-selector__scope-chip:has(input:checked) {
  border-color: rgb(var(--evergreen) / 0.45);
  background: rgb(var(--evergreen) / 0.08);
  color: rgb(var(--evergreen));
}

.permission-selector__selection-hint {
  display: inline-flex;
  align-items: center;
  min-height: 1.5rem;
  border-radius: 999px;
  background: rgb(var(--paper-deep));
  padding: 0.15rem 0.55rem;
  color: rgb(var(--ink-soft));
  font-size: 12px;
  font-weight: 600;
}

@keyframes permissionSelectorRowEnter {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes permissionSelectorRowExit {
  from {
    opacity: 1;
    transform: translateY(0);
  }
  to {
    opacity: 0;
    transform: translateY(-4px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .permission-selector__row:not(.permission-selector__row--group),
  .permission-selector__row--exiting {
    animation: none;
  }

  .permission-selector__toolbar-toggle-track,
  .permission-selector__toolbar-toggle-thumb,
  .permission-selector__chevron {
    transition: none;
  }
}
```

- [ ] **步骤 8: 把根容器 class 改为专属 surface**

把返回 JSX 的根容器从：

```tsx
    <div className="paper-card overflow-hidden rounded-[3px] p-0">
```

改为：

```tsx
    <div className="permission-selector__surface">
```

- [ ] **步骤 9: 运行门户测试**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx
```

预期：`PortalPage.test.tsx` 全部通过。

- [ ] **步骤 10: 提交视觉重构**

提交：

```bash
git add frontend/src/pages/portal/components/PermissionSelector.tsx frontend/src/styles/features/permission-selector.css frontend/src/pages/portal/PortalPage.test.tsx
git commit -m "style: refresh portal permission selector table"
```

---

### 任务 4: 强化表格架构测试

**文件：**
- 修改：`frontend/src/components/tableArchitecture.test.ts`

- [ ] **步骤 1: 扩展 TanStack 原始构建断言**

把 `门户权限选择表格直接使用 TanStack Table 渲染原生表格` 测试扩展为：

```ts
  test("门户权限选择表格直接使用 TanStack Table 渲染原生表格", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).not.toMatch(/components\/ui\/TablePrimitives/);
    expect(content).not.toMatch(/components\/ui\/TablePagination/);
    expect(content).not.toMatch(/\bDataTable\b/);
    expect(content).not.toMatch(/\bTableFrame\b/);
    expect(content).not.toMatch(/\bTableRoot\b/);
    expect(content).not.toMatch(/\bTableEmptyRow\b/);
    expect(content).toMatch(/useReactTable/);
    expect(content).toMatch(/getCoreRowModel/);
    expect(content).toMatch(/getPaginationRowModel/);
    expect(content).toMatch(/getRowId/);
    expect(content).toMatch(/flexRender/);
    expect(content).toMatch(/<table\b/);
    expect(content).toMatch(/aria-label="权限选择"/);
  });
```

- [ ] **步骤 2: 增加过滤和工具条局部实现断言**

在同一个 `describe("表格架构", () => {` 内新增测试：

```ts
  test("门户权限选择仅看已选是组件内本地展示状态", () => {
    const file = join(sourceRoot, "pages/portal/components/PermissionSelector.tsx");
    const content = readFileSync(file, "utf8");

    expect(content).toMatch(/showSelectedOnly/);
    expect(content).toMatch(/filterRowsToSelected/);
    expect(content).toMatch(/buildPermissionSelectorToolbarStats/);
    expect(content).toMatch(/role="switch"/);
    expect(content).toMatch(/aria-label="仅看已选"/);
  });
```

- [ ] **步骤 3: 运行架构测试，确认通过**

运行：

```bash
pnpm --dir frontend test frontend/src/components/tableArchitecture.test.ts
```

预期：`tableArchitecture.test.ts` 全部通过。

- [ ] **步骤 4: 提交架构测试**

提交：

```bash
git add frontend/src/components/tableArchitecture.test.ts
git commit -m "test: guard portal permission selector table architecture"
```

---

### 任务 5: 全量验证与真实页面加载确认

**文件：**
- 验证：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 验证：`frontend/src/styles/features/permission-selector.css`
- 验证：`frontend/src/pages/portal/PortalPage.test.tsx`
- 验证：`frontend/src/components/tableArchitecture.test.ts`

- [ ] **步骤 1: 运行目标前端测试**

运行：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx frontend/src/components/tableArchitecture.test.ts
```

预期：两个测试文件全部通过，输出中无 failed tests。

- [ ] **步骤 2: 运行 TypeScript 检查**

运行：

```bash
pnpm --dir frontend typecheck
```

预期：退出码 `0`。

- [ ] **步骤 3: 构建前端**

运行：

```bash
pnpm --dir frontend build
```

预期：`tsc -b && vite build` 成功，输出新的 `src/easyauth/static/easyauth/frontend/.vite/manifest.json` 和 `assets/main-*.js`、`assets/main-*.css`。

- [ ] **步骤 4: 运行 Django check**

运行：

```bash
.venv/bin/python manage.py check
```

预期：输出 `System check identified no issues (0 silenced).`

- [ ] **步骤 5: 重启 Django 开发服务**

如果 `8001` 是当前 EasyAuth dev server，先定位并停止：

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
kill <PID>
```

然后启动：

```bash
DJANGO_DEBUG=1 EASYAUTH_ENABLE_DEV_LOGIN=1 .venv/bin/python manage.py runserver 0.0.0.0:8001 --noreload
```

如果当前开发服务使用其他端口，按实际端口重启，不要碰与 EasyAuth 无关的服务。

- [ ] **步骤 6: 验证真实 `/portal/request` 页面加载新 build**

先读取最新 manifest：

```bash
cat src/easyauth/static/easyauth/frontend/.vite/manifest.json
```

记录其中 `assets/main-*.js` 和 `assets/main-*.css` 文件名，然后使用 dev login 请求真实页面：

```bash
curl -sS -L -c /tmp/easyauth-dev-cookies.txt -b /tmp/easyauth-dev-cookies.txt \
  "http://127.0.0.1:8001/auth/dev-login/?user_id=dev-user&next=/portal/request" \
  -o /tmp/easyauth-portal-request.html \
  -w "%{http_code} %{url_effective}\n"
```

预期：输出 `200 http://127.0.0.1:8001/portal/request`。

验证 HTML 引用最新资源：

```bash
rg -n "main-.*\\.js|main-.*\\.css|/static/easyauth/frontend" /tmp/easyauth-portal-request.html
```

预期：输出包含 manifest 中的最新 `main-*.js` 和 `main-*.css`。

- [ ] **步骤 7: 最终状态检查**

运行：

```bash
git status --short
```

预期：没有未提交源码、测试或文档变更。`src/easyauth/static/easyauth/frontend` 下 build 产物按 `.gitignore` 忽略，不应进入提交。

---

## 实施注意事项

- 每个实现任务完成后必须 commit，不要把红灯测试单独提交。
- 不得用 `TablePrimitives`、`TablePagination` 或任何新表格包装组件承接本次改造。
- 不得新增兼容旧表格 class 的样式层。
- 不得让“仅看已选”影响提交 payload。
- 不得删除 checkbox/select 的 `stopPropagation`。
- 不得破坏 `useExitingGroupKeys` 的 memo 返回和 `stringListsAreEqual(current, next) ? current : next` guard。
- 视觉样式保持克制密集，不改成卡片列表或营销式布局。
- 文档、提交信息和新增说明使用中文；代码标识符、路径、命令和专有名词可保持英文。

## 计划自审

- 覆盖规格中的顶部工具条、树形层级、已选态、多 scope 语义、过滤、空状态、分页和验证要求。
- 实施范围仅包含 `PermissionSelector`、其专属样式和对应测试，不触碰后端 API 与提交数据模型。
- 计划没有引入表格兼容层或旧表格包装组件。
- 每个代码步骤都有明确文件、代码片段、命令和预期结果。
