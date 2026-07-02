# 门户权限范围表格修复实施计划

> **给自动化执行者:** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 逐任务实施本计划。步骤使用 checkbox（`- [ ]`）语法跟踪。

**目标:** 修复门户申请权限表格展开后的文字重叠、`scope` 未中文化、父子条目选择样式不一致、工具条操作缺失和分页选择状态丢失风险。

**架构:** 继续以 `PermissionSelector` 作为表格交互边界，不改后端 API，不新增兼容字段。把选择语义收敛到“权限范围”列，父组和子权限共用 chip 选择控件；选择状态仍由 `useAccessRequestForm` 的 `selectedPermissionKeys` 表示，并在提交时输出明确的 `permission + scope` 原子 grant。工具条操作只作用于点击前当前页的 rows，父组 row 代表其整棵权限子树。

**技术栈:** React、TypeScript、TanStack Table、Testing Library、Vitest、Tailwind CSS、Django。

---

## 规格决策

- 表头 `scope` 改为“权限范围”，工具条可见文案不得出现英文 `scope`。
- 删除独立“选择”列，选择全部在“权限范围”列完成。
- 父条目不再使用“批量应用 scope”下拉框，改为和子条目完全一致的权限范围 chip。
- 单权限范围和多权限范围都使用 chip；点击 chip 选择或取消对应 `permission + scope` grant。
- 权限范围递增关系以当前权限 `scopes` 数组顺序为准；后端目录当前按 `AppScope.display_order, key` 返回该数组。
- 选择高层权限范围时，自动补齐该权限支持列表中更低层的范围；取消低层权限范围时，自动取消该权限支持列表中该项及更高层的范围。
- 递增只在权限实际支持的 `scopes` 内生效，不生成 unsupported grant。
- 父条目 chip 按整棵子树计算三态；点击未选或半选 chip 选中所有支持该范围的子权限，并按递增规则补齐；点击已选 chip 取消所有支持该范围的子权限，并按递增规则移除更高层范围。
- 工具条新增 `展开全部`、`折叠全部`、`全选`、`清空`，全部只作用于点击前当前页已有 rows。
- 当前页出现父条目时，工具条 `全选` 和 `清空` 操作该父条目的整棵子树；当前页同时出现父条目和其子条目时必须去重，避免重复处理。
- `全选` 选择每个命中子权限支持的全部权限范围；`清空` 删除每个命中子权限的全部权限范围。
- 翻页不得清空 `selectedPermissionKeys` 或 `selectedPermissionScopes`；分页只影响当前页批量操作范围。
- 表格展开后 chip 不允许文字重叠；“本人 / 管理范围 / 全部”优先单行显示，窄屏使用表格横向滚动。

## 文件结构

- 修改：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts`
  - 负责权限范围递增选择算法、父组批量选择算法、提交 payload。
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
  - 负责列结构、父子 chip、工具条按钮、当前页 rows 作用域、分页展示。
- 修改：`frontend/src/styles/features/permission-selector.css`
  - 负责 chip 一行布局、权限范围列最小宽度、三态视觉和工具条按钮样式。
- 修改：`frontend/src/pages/portal/PortalPage.test.tsx`
  - 覆盖中文表头、删除选择列、父子 chip、一行布局语义、递增选择、父组三态、当前页工具条、分页保持选择。
- 可选修改：`frontend/src/components/tableArchitecture.test.ts`
  - 只有当列结构或 helper 命名触发架构测试时调整断言，禁止借机引入通用表格包装层。

## 并行分工建议

- 子代理 A：只修改 `frontend/src/pages/portal/hooks/useAccessRequestForm.ts` 和相关单元级测试片段。
- 子代理 B：只修改 `frontend/src/pages/portal/components/PermissionSelector.tsx`。
- 子代理 C：只修改 `frontend/src/styles/features/permission-selector.css`。
- 主代理：整合测试、处理冲突、运行验证、提交 commit、构建和必要的 Django 重启验证。

并行时禁止多个代理同时编辑同一个文件。`PortalPage.test.tsx` 最好由主代理或最后一个集成代理统一修改，因为它会同时验证 hook、组件和样式语义。

---

### 任务 1: 先写失败测试

**文件:**
- 修改：`frontend/src/pages/portal/PortalPage.test.tsx`

- [ ] **步骤 1: 扩展测试 fixture**

把 `portalPermissionSelectorCatalog` 中多权限范围权限改成递增业务口径，确保至少包含 `SELF`、`MANAGED_USERS`、`ALL`：

```ts
{
  id: 103,
  app_key: "crm",
  key: "orders.refund.approve",
  name: "审批退款",
  scopes: [
    { key: "SELF", name: "本人" },
    { key: "MANAGED_USERS", name: "管理范围" },
    { key: "ALL", name: "全部" },
  ],
}
```

保留一个单权限范围权限：

```ts
{ id: 102, app_key: "crm", key: "orders.export", name: "导出订单", scopes: [{ key: "SELF", name: "本人" }] }
```

- [ ] **步骤 2: 增加中文表头和删除选择列测试**

追加或替换现有“权限选择表格保留表头语义”测试中的表头断言：

```ts
expect(within(permissionTable).getByRole("columnheader", { name: "权限" })).toBeVisible();
expect(within(permissionTable).getByRole("columnheader", { name: "权限 key" })).toBeVisible();
expect(within(permissionTable).getByRole("columnheader", { name: "权限范围" })).toBeVisible();
expect(within(permissionTable).queryByRole("columnheader", { name: "scope" })).not.toBeInTheDocument();
expect(within(permissionTable).queryByRole("columnheader", { name: "选择" })).not.toBeInTheDocument();
expect(screen.getByText("已设置权限范围 3 项")).toBeVisible();
expect(screen.queryByText(/当前显示/)).not.toBeInTheDocument();
```

- [ ] **步骤 3: 增加单权限范围 chip 测试**

追加测试，确认单权限范围不再通过独立选择列 checkbox 选择：

```ts
test("单权限范围权限通过权限范围 chip 选择", async () => {
  const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
  vi.stubGlobal("fetch", fetchMock);

  try {
    renderPortalPage();
    const user = userEvent.setup();

    await screen.findByRole("option", { name: "CRM (crm)" });
    await user.selectOptions(screen.getByLabelText("应用"), "crm");
    const permissionTable = await screen.findByRole("table", { name: "权限选择" });

    await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
    const selfChip = within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" });
    expect(selfChip).not.toBeChecked();

    await user.click(selfChip);
    expect(selfChip).toBeChecked();
    expect(screen.getByText("已选 1 项")).toBeVisible();

    await user.click(selfChip);
    expect(selfChip).not.toBeChecked();
    expect(screen.getByText("已选 0 项")).toBeVisible();
  } finally {
    vi.unstubAllGlobals();
  }
});
```

- [ ] **步骤 4: 增加递增权限范围测试**

追加测试，确认选择高层自动补齐低层，取消低层自动取消高层：

```ts
test("多权限范围按递增关系自动补齐和收缩", async () => {
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

    const self = within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" });
    const managed = within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理范围" });
    const all = within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" });

    await user.click(all);
    expect(self).toBeChecked();
    expect(managed).toBeChecked();
    expect(all).toBeChecked();
    expect(screen.getByText("已选 3 项")).toBeVisible();

    await user.click(self);
    expect(self).not.toBeChecked();
    expect(managed).not.toBeChecked();
    expect(all).not.toBeChecked();
    expect(screen.getByText("已选 0 项")).toBeVisible();
  } finally {
    vi.unstubAllGlobals();
  }
});
```

- [ ] **步骤 5: 增加父条目 chip 三态和整棵子树操作测试**

追加测试，确认父条目点击 `全部` 操作子树，且子权限部分选择时父 chip 半选：

```ts
test("父条目权限范围 chip 操作整棵子树并显示半选态", async () => {
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

    const parentAll = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" });
    await user.click(parentAll);

    expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).toBeChecked();
    expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理范围" })).toBeChecked();
    expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).toBeChecked();

    await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" }));
    expect(parentAll).toHaveAttribute("aria-checked", "mixed");
  } finally {
    vi.unstubAllGlobals();
  }
});
```

- [ ] **步骤 6: 增加当前页工具条和分页保持选择测试**

追加测试，确认 `全选` 只作用当前页，翻页后已选不丢失：

```ts
test("工具条只操作当前页且翻页保留已选权限范围", async () => {
  const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
  vi.stubGlobal("fetch", fetchMock);

  try {
    renderPortalPage();
    const user = userEvent.setup();

    await screen.findByRole("option", { name: "CRM (crm)" });
    await user.selectOptions(screen.getByLabelText("应用"), "crm");
    const permissionTable = await screen.findByRole("table", { name: "权限选择" });

    await user.selectOptions(screen.getByLabelText("每页条目数"), "5");
    await user.click(screen.getByRole("button", { name: "展开全部" }));
    await user.click(screen.getByRole("button", { name: "全选" }));

    expect(screen.getByText(/已选 [1-9]\d* 项/)).toBeVisible();

    if (screen.queryByRole("button", { name: "下一页" })?.hasAttribute("disabled") === false) {
      await user.click(screen.getByRole("button", { name: "下一页" }));
      expect(screen.getByText(/已选 [1-9]\d* 项/)).toBeVisible();
      await user.click(screen.getByRole("button", { name: "上一页" }));
    }

    await user.click(screen.getByRole("button", { name: "清空" }));
    expect(screen.getByText("已选 0 项")).toBeVisible();
  } finally {
    vi.unstubAllGlobals();
  }
});
```

- [ ] **步骤 7: 运行测试确认失败**

运行：

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx
```

预期：至少因为表头仍为 `scope`、仍存在“选择”列、单 scope 仍为下拉框、工具条按钮不存在而失败。

- [ ] **步骤 8: 提交测试**

```bash
git add frontend/src/pages/portal/PortalPage.test.tsx
git commit -m "test: 覆盖门户权限范围表格修复口径"
```

---

### 任务 2: 改造权限范围选择状态算法

**文件:**
- 修改：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts`

- [ ] **步骤 1: 增加权限范围选择 helper**

在 `directGrantSelectionScopeKey` 后加入 helper，用于递增选择：

```ts
function permissionScopeSelectionKey(permissionKey: string, scopeKey: string): string {
  return directGrantSelectionKey(permissionKey, scopeKey);
}

function permissionScopeKeys(permission: ScopedPermissionItem): string[] {
  return (permission.scopes ?? []).map((scope) => scope.key);
}

function selectedScopeKeysForPermission(permissionKey: string, selectedKeys: string[]): string[] {
  return selectedKeys
    .filter((selectionKey) => directGrantSelectionPermissionKey(selectionKey) === permissionKey)
    .map((selectionKey) => directGrantSelectionScopeKey(selectionKey))
    .filter((scopeKey): scopeKey is string => Boolean(scopeKey));
}

function nextPermissionScopeSelection(
  permission: ScopedPermissionItem,
  scopeKey: string,
  selectedKeys: string[],
): string[] {
  const scopeKeys = permissionScopeKeys(permission);
  const scopeIndex = scopeKeys.indexOf(scopeKey);
  if (scopeIndex === -1) {
    return selectedKeys;
  }

  const selectedScopeKeys = new Set(selectedScopeKeysForPermission(permission.key, selectedKeys));
  const shouldSelect = !selectedScopeKeys.has(scopeKey);
  const affectedScopeKeys = shouldSelect ? scopeKeys.slice(0, scopeIndex + 1) : scopeKeys.slice(scopeIndex);
  const affectedSelectionKeys = new Set(affectedScopeKeys.map((key) => permissionScopeSelectionKey(permission.key, key)));
  const retainedKeys = selectedKeys.filter((selectionKey) => !affectedSelectionKeys.has(selectionKey));

  if (!shouldSelect) {
    return retainedKeys;
  }
  return uniqueStrings([...retainedKeys, ...affectedSelectionKeys]);
}
```

- [ ] **步骤 2: 改造单权限选择 key 生成**

替换 `permissionSelectionKeys`，让单 scope 也统一生成 `permission::scope::scopeKey`，不再使用裸 `permission.key`：

```ts
function permissionSelectionKeys(permission: ScopedPermissionItem): string[] {
  return permissionScopeKeys(permission).map((scopeKey) => directGrantSelectionKey(permission.key, scopeKey));
}
```

- [ ] **步骤 3: 改造 `togglePermission` action**

把 `togglePermission` 改为兼容新 chip 选择 key 的实现：

```ts
togglePermission: (key: string) => {
  fields.setSelectedPermissionKeys((current) => toggleListItem(current, key));
},
```

该步骤保留函数签名，后续 `PermissionSelector` 传入的 key 一律是 `permission::scope::scopeKey`。

- [ ] **步骤 4: 新增按权限对象切换权限范围的 action**

把 `AccessRequestActions` 和 `AccessRequestFormResult` 中的 `changePermissionScope` 签名改成：

```ts
changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => void;
```

实现改为：

```ts
changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => {
  fields.setSelectedPermissionKeys((current) => nextPermissionScopeSelection(permission, scopeKey, current));
},
```

删除 `fields.setSelectedPermissionScopes((current) => ({ ...current, [permissionKey]: scopeKey }))` 这类下拉框状态更新。

- [ ] **步骤 5: 改造父组范围选择 action**

把 `AccessRequestActions` 和 `AccessRequestFormResult` 中的 `changePermissionGroupScope` 签名改成：

```ts
changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
```

实现为：

```ts
changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => {
  const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) =>
    permissionScopeKeys(permission).includes(scopeKey),
  );

  fields.setSelectedPermissionKeys((current) => {
    let next = current;
    for (const permission of supportedPermissions) {
      const scopeKeys = permissionScopeKeys(permission);
      const scopeIndex = scopeKeys.indexOf(scopeKey);
      const affectedScopeKeys = shouldSelect ? scopeKeys.slice(0, scopeIndex + 1) : scopeKeys.slice(scopeIndex);
      const affectedSelectionKeys = affectedScopeKeys.map((key) => directGrantSelectionKey(permission.key, key));
      next = shouldSelect
        ? uniqueStrings([...next, ...affectedSelectionKeys])
        : next.filter((selectionKey) => !affectedSelectionKeys.includes(selectionKey));
    }
    return next;
  });
},
```

- [ ] **步骤 6: 提交 payload 保持显式 grant**

确认 `buildAccessRequestPayload` 对每个 selection key 输出显式 scope：

```ts
direct_grants: values.selectedPermissionKeys.map((permissionKey) => ({
  permission: directGrantSelectionPermissionKey(permissionKey),
  scope: directGrantSelectionScopeKey(permissionKey) ?? values.selectedPermissionScopes[permissionKey],
})),
```

在任务 4 完成后，所有 direct selection key 都应包含 scope；保留 `selectedPermissionScopes` 兜底只服务现有未清理状态，不新增可见交互。

- [ ] **步骤 7: 运行测试确认仍失败在组件层**

运行：

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx
```

预期：hook 类型错误或组件仍调用旧签名导致失败；修复将在任务 3 完成。

- [ ] **步骤 8: 提交状态算法**

```bash
git add frontend/src/pages/portal/hooks/useAccessRequestForm.ts
git commit -m "feat: 支持递增权限范围选择状态"
```

---

### 任务 3: 重构 `PermissionSelector` 列和父子 chip

**文件:**
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`

- [ ] **步骤 1: 删除选择列**

从 `columns` 删除 `id: "selection"` 整列，保留三列：

```ts
id: "permission"
id: "key"
id: "scope"
```

把 `scope` 表头改为：

```ts
header: "权限范围",
```

- [ ] **步骤 2: 调整 props 签名**

把 props 中两个 handler 改成：

```ts
onPermissionScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
onPermissionGroupScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
```

- [ ] **步骤 3: 增加权限范围 chip 状态类型**

在 `GroupSelectionState` 附近加入：

```ts
type ScopeSelectionState = "checked" | "indeterminate" | "unchecked";
```

- [ ] **步骤 4: 用父子共用 chip 替换父组下拉框**

删除 `PermissionGroupScopeCell` 中的 `SelectInput` 实现，替换为：

```tsx
function PermissionGroupScopeCell({
  group,
  scopeOptions,
  selectedKeys,
  onScopeChange,
}: {
  group: ScopedPermissionGroupItem;
  scopeOptions: string[];
  selectedKeys: string[];
  onScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
}) {
  if (scopeOptions.length === 0) {
    return <span aria-label="权限组无权限范围">-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopeOptions.map((scopeKey) => {
        const state = groupScopeSelectionState(group, scopeKey, selectedKeys);
        return (
          <ScopeChip
            key={scopeKey}
            label={scopeKey}
            checked={state === "checked"}
            mixed={state === "indeterminate"}
            ariaLabel={`选择权限组 ${group.key} ${scopeKey}`}
            onChange={() => onScopeChange(group, scopeKey, state !== "checked")}
          />
        );
      })}
    </div>
  );
}
```

- [ ] **步骤 5: 用 chip 替换子权限下拉框**

把 `PermissionScopeCell` 改为所有权限范围统一 chip：

```tsx
function PermissionScopeCell({
  permission,
  selectedKeys,
  onScopeChange,
}: {
  permission: ScopedPermissionItem;
  selectedKeys: string[];
  onScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
}) {
  const scopes = permission.scopes ?? [];
  if (scopes.length === 0) {
    return <span aria-label={`${permission.key} 无权限范围`}>-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopes.map((scope) => {
        const selectionKey = directGrantSelectionKey(permission.key, scope.key);
        return (
          <ScopeChip
            key={scope.key}
            label={scope.name}
            checked={selectedKeys.includes(selectionKey)}
            mixed={false}
            ariaLabel={`选择 ${permission.key} ${scope.name}`}
            onChange={() => onScopeChange(permission, scope.key)}
          />
        );
      })}
    </div>
  );
}
```

- [ ] **步骤 6: 新增共用 `ScopeChip`**

加入组件：

```tsx
function ScopeChip({
  label,
  checked,
  mixed,
  ariaLabel,
  onChange,
}: {
  label: string;
  checked: boolean;
  mixed: boolean;
  ariaLabel: string;
  onChange: () => void;
}) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = mixed;
    }
  }, [mixed]);

  return (
    <label
      className={joinClassNames(
        "permission-selector__scope-chip",
        checked && "permission-selector__scope-chip--checked",
        mixed && "permission-selector__scope-chip--mixed",
      )}
    >
      <input
        ref={checkboxRef}
        type="checkbox"
        checked={checked}
        aria-checked={mixed ? "mixed" : checked}
        onClick={(event) => event.stopPropagation()}
        onChange={onChange}
        aria-label={ariaLabel}
      />
      <span>{label}</span>
    </label>
  );
}
```

- [ ] **步骤 7: 增加父组 chip 三态 helper**

加入 helper：

```ts
function groupScopeSelectionState(group: ScopedPermissionGroupItem, scopeKey: string, selectedKeys: string[]): ScopeSelectionState {
  const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) =>
    (permission.scopes ?? []).some((scope) => scope.key === scopeKey),
  );
  if (supportedPermissions.length === 0) {
    return "unchecked";
  }

  const selectedCount = supportedPermissions.filter((permission) =>
    selectedKeys.includes(directGrantSelectionKey(permission.key, scopeKey)),
  ).length;
  if (selectedCount === 0) {
    return "unchecked";
  }
  return selectedCount === supportedPermissions.length ? "checked" : "indeterminate";
}
```

- [ ] **步骤 8: 修正已选判断**

确认 `isPermissionSelected` 对新 selection key 仍正确：

```ts
function isPermissionSelected(permissionKey: string, selectedKeys: string[]): boolean {
  return selectedKeys.some((key) => directGrantSelectionPermissionKey(key) === permissionKey);
}
```

- [ ] **步骤 9: 删除旧选择单元**

删除 `PermissionGroupSelectionCell` 和 `PermissionSelectionCell`，以及不再使用的 `SelectInput` import。

- [ ] **步骤 10: 运行测试**

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx
```

预期：表头、选择列、chip 相关测试通过；工具条按钮测试仍可能失败。

- [ ] **步骤 11: 提交组件列重构**

```bash
git add frontend/src/pages/portal/components/PermissionSelector.tsx
git commit -m "feat: 统一门户权限范围选择列"
```

---

### 任务 4: 增加当前页工具条操作

**文件:**
- 修改：`frontend/src/pages/portal/components/PermissionSelector.tsx`
- 修改：`frontend/src/pages/portal/hooks/useAccessRequestForm.ts`

- [ ] **步骤 1: 在 hook 暴露批量选择 action**

在 `AccessRequestActions` 和 `AccessRequestFormResult` 增加：

```ts
selectPermissionKeys: (selectionKeys: string[]) => void;
clearPermissionKeys: (selectionKeys: string[]) => void;
expandGroups: (groupKeys: string[]) => void;
collapseGroups: (groupKeys: string[]) => void;
```

在 `buildAccessRequestActions` 中实现：

```ts
selectPermissionKeys: (selectionKeys: string[]) => {
  fields.setSelectedPermissionKeys((current) => uniqueStrings([...current, ...selectionKeys]));
},
clearPermissionKeys: (selectionKeys: string[]) => {
  const selectionKeySet = new Set(selectionKeys);
  fields.setSelectedPermissionKeys((current) => current.filter((key) => !selectionKeySet.has(key)));
},
expandGroups: (groupKeys: string[]) => {
  fields.setExpandedGroupKeys((current) => uniqueStrings([...current, ...groupKeys]));
},
collapseGroups: (groupKeys: string[]) => {
  const groupKeySet = new Set(groupKeys);
  fields.setExpandedGroupKeys((current) => current.filter((key) => !groupKeySet.has(key)));
},
```

- [ ] **步骤 2: 把新 action 透传到 `PermissionSelector`**

更新 `RequestTargetPicker.tsx` 和 `AccessRequestForm.tsx` 的 props，透传：

```tsx
onSelectPermissionKeys={form.selectPermissionKeys}
onClearPermissionKeys={form.clearPermissionKeys}
onExpandGroups={form.expandGroups}
onCollapseGroups={form.collapseGroups}
```

- [ ] **步骤 3: 在 `PermissionSelectorProps` 增加工具条 handler**

```ts
onSelectPermissionKeys: (selectionKeys: string[]) => void;
onClearPermissionKeys: (selectionKeys: string[]) => void;
onExpandGroups: (groupKeys: string[]) => void;
onCollapseGroups: (groupKeys: string[]) => void;
```

- [ ] **步骤 4: 当前页 rows 计算作用范围**

在 `PermissionSelector` 内根据 `visibleRows` 计算：

```ts
const currentPageGroupKeys = useMemo(
  () => visibleRows.map((row) => row.original).filter((row) => row.type === "group").map((row) => row.group.key),
  [visibleRows],
);
const currentPageSelectionKeys = useMemo(
  () => currentPageSelectionKeysFromRows(visibleRows.map((row) => row.original)),
  [visibleRows],
);
```

加入 helper：

```ts
function currentPageSelectionKeysFromRows(rows: PermissionSelectorRow[]): string[] {
  const permissionByKey = new Map<string, ScopedPermissionItem>();
  for (const row of rows) {
    if (row.type === "permission") {
      permissionByKey.set(row.permission.key, row.permission);
      continue;
    }
    for (const permission of collectScopedGroupPermissions(row.group)) {
      permissionByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionByKey.values()).flatMap((permission) => permissionSelectionKeys(permission));
}
```

- [ ] **步骤 5: 改造工具条 props**

把 `PermissionSelectorToolbar` props 改成：

```ts
selectedCount: number;
configuredScopeCount: number;
showSelectedOnly: boolean;
onShowSelectedOnlyChange: (showSelectedOnly: boolean) => void;
onExpandCurrentPage: () => void;
onCollapseCurrentPage: () => void;
onSelectCurrentPage: () => void;
onClearCurrentPage: () => void;
canOperateCurrentPage: boolean;
```

- [ ] **步骤 6: 工具条渲染按钮**

替换工具条统计中的“当前显示”并增加按钮：

```tsx
<div className="permission-selector__toolbar-actions" aria-label="权限表格操作">
  <button type="button" className="permission-selector__toolbar-button" disabled={!canOperateCurrentPage} onClick={onExpandCurrentPage}>
    展开全部
  </button>
  <button type="button" className="permission-selector__toolbar-button" disabled={!canOperateCurrentPage} onClick={onCollapseCurrentPage}>
    折叠全部
  </button>
  <button type="button" className="permission-selector__toolbar-button" disabled={!canOperateCurrentPage} onClick={onSelectCurrentPage}>
    全选
  </button>
  <button type="button" className="permission-selector__toolbar-button" disabled={!canOperateCurrentPage} onClick={onClearCurrentPage}>
    清空
  </button>
</div>
```

统计保留：

```tsx
<span className="permission-selector__toolbar-stat">已选 {selectedCount} 项</span>
<span className="permission-selector__toolbar-stat">已设置权限范围 {configuredScopeCount} 项</span>
```

- [ ] **步骤 7: 绑定当前页操作**

调用工具条时绑定：

```tsx
onExpandCurrentPage={() => onExpandGroups(currentPageGroupKeys)}
onCollapseCurrentPage={() => onCollapseGroups(currentPageGroupKeys)}
onSelectCurrentPage={() => onSelectPermissionKeys(currentPageSelectionKeys)}
onClearCurrentPage={() => onClearPermissionKeys(currentPageSelectionKeys)}
canOperateCurrentPage={visibleRows.length > 0}
```

- [ ] **步骤 8: 运行测试**

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx
```

预期：当前页工具条和分页保持选择测试通过。

- [ ] **步骤 9: 提交工具条改造**

```bash
git add frontend/src/pages/portal/components/PermissionSelector.tsx frontend/src/pages/portal/hooks/useAccessRequestForm.ts frontend/src/pages/portal/components/RequestTargetPicker.tsx frontend/src/pages/portal/components/AccessRequestForm.tsx
git commit -m "feat: 增加门户权限表格当前页批量操作"
```

---

### 任务 5: 修复样式重叠和权限范围列布局

**文件:**
- 修改：`frontend/src/styles/features/permission-selector.css`

- [ ] **步骤 1: 给权限范围列稳定宽度**

增加 class：

```css
.permission-selector__scope-cell {
  min-width: 18rem;
  white-space: nowrap;
}
```

在 `PermissionSelector.tsx` 的 `<td>` className 中，当 `cell.column.id === "scope"` 时追加：

```ts
cell.column.id === "scope" && "permission-selector__scope-cell",
```

- [ ] **步骤 2: 固定 chip 行为单行排列**

替换或扩展现有 chip list：

```css
.permission-selector__scope-chip-list {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  max-width: 100%;
}

.permission-selector__scope-chip-list--single-line {
  flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: thin;
}
```

- [ ] **步骤 3: 防止 chip 文本压缩重叠**

更新 chip 样式：

```css
.permission-selector__scope-chip {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 0.45rem;
  min-height: 1.875rem;
  border: 1px solid rgb(var(--hairline-strong));
  border-radius: 999px;
  background: rgb(var(--paper));
  padding: 0.3rem 0.6rem;
  color: rgb(var(--ink-soft));
  font-size: 12px;
  font-weight: 650;
  line-height: 1;
  white-space: nowrap;
}

.permission-selector__scope-chip input {
  flex: 0 0 auto;
}
```

- [ ] **步骤 4: 增加半选样式**

```css
.permission-selector__scope-chip--mixed {
  border-color: rgb(var(--amber) / 0.55);
  background: rgb(var(--amber) / 0.1);
  color: rgb(var(--ink));
}
```

- [ ] **步骤 5: 增加工具条按钮样式**

```css
.permission-selector__toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.permission-selector__toolbar-button {
  display: inline-flex;
  min-height: 1.875rem;
  align-items: center;
  justify-content: center;
  border: 1px solid rgb(var(--hairline-strong));
  border-radius: 3px;
  background: rgb(var(--paper));
  padding: 0.25rem 0.65rem;
  color: rgb(var(--ink));
  font-size: 12px;
  font-weight: 700;
  transition: border-color 160ms var(--ease-press), background 160ms var(--ease-press);
}

.permission-selector__toolbar-button:hover {
  border-color: rgb(var(--amber));
  background: rgb(var(--amber) / 0.08);
}

.permission-selector__toolbar-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}
```

- [ ] **步骤 6: 检查颜色主题**

运行：

```bash
rg -n "permission-selector__scope|permission-selector__toolbar" frontend/src/styles/features/permission-selector.css
```

预期：只看到本任务新增或调整的 selector；不引入大面积单色渐变主题。

- [ ] **步骤 7: 运行测试**

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx
```

预期：通过。

- [ ] **步骤 8: 提交样式**

```bash
git add frontend/src/styles/features/permission-selector.css frontend/src/pages/portal/components/PermissionSelector.tsx
git commit -m "fix: 修复门户权限范围表格布局重叠"
```

---

### 任务 6: 全量验证、构建、运行页面验证

**文件:**
- 不新增文件。
- 可能修改：前面任务涉及的前端文件。

- [ ] **步骤 1: 运行门户前端测试**

```bash
pnpm --dir frontend test -- --run src/pages/portal/PortalPage.test.tsx src/pages/portal/permissionTree.test.ts
```

预期：全部通过。

- [ ] **步骤 2: 运行前端构建**

```bash
pnpm --dir frontend build
```

预期：构建成功，更新 Vite build 产物和 manifest。

- [ ] **步骤 3: 运行后端检查**

```bash
.venv/bin/python manage.py check
```

预期：`System check identified no issues`。

- [ ] **步骤 4: 提交构建产物**

检查变更：

```bash
git status --short
```

提交：

```bash
git add frontend src static docs
git commit -m "fix: 修复门户申请权限范围表格"
```

如果前面任务已经按小步提交，最终提交只包含构建产物或集成修正。

- [ ] **步骤 5: 重启 Django 开发服务**

如果当前有 Django 开发服务，停止并重启。优先使用项目既有命令；没有既有脚本时运行：

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8000
```

预期：服务监听 `http://127.0.0.1:8000/`。

- [ ] **步骤 6: 真实页面验证新代码已加载**

打开：

```text
http://127.0.0.1:8000/portal/request
```

验证：

- 表格表头显示“权限范围”。
- 页面不显示“当前显示 x/y”。
- 页面不显示独立“选择”列。
- 工具条显示 `展开全部`、`折叠全部`、`全选`、`清空`。
- 展开订单父条目后，父子条目都显示相同 chip 样式。
- 选择“全部”后，“本人”和“管理范围”自动勾选。
- 翻到下一页再返回，已选权限范围仍保持勾选。

---

## 自检清单

- [ ] 文档正文为中文；英文只保留代码标识符、命令、路径、库名和协议字段。
- [ ] 没有新增兼容字段、兼容分支或后端隐式推导。
- [ ] 没有使用 mock 掩盖业务事实；测试 mock 只隔离 `fetch`。
- [ ] 选择状态的单一事实来源仍是 `selectedPermissionKeys`。
- [ ] 提交 payload 仍是显式 `direct_grants: [{ permission, scope }]`。
- [ ] 当前页批量操作以点击前 `visibleRows` 为作用范围。
- [ ] 父组当前页批量操作覆盖整棵子树。
- [ ] `全选` 和 `清空` 不影响非当前页 selection key。
- [ ] 展开和折叠全部只作用当前页父组 key。
- [ ] 构建后按项目规则提交 commit，并在修改运行页面响应后重启 Django 开发服务做真实页面验证。
