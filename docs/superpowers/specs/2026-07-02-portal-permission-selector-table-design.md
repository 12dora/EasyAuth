# 门户权限选择表格视觉与交互重构设计

## 背景

门户“申请权限”表单中的“直接权限”选择表格已经改为直接使用 TanStack Table 的 `useReactTable`、row model 和原生 `<table>` 渲染。当前实现满足功能与架构约束，但视觉上仍显粗糙：权限组、权限项、`permission key`、`scope` 和选择控件被平铺在同一层级里，树形关系弱，已选状态反馈弱，多 `scope` 权限容易被误读为不可选，分页状态也不像一个完整的权限核对面板。

本设计用于指导后续实现。当前阶段只确认设计，不实施代码。

## 目标

- 将权限选择表格重构为“审计控制台式权限篮”：紧凑、克制、清晰，优先服务权限申请人核对权限、`scope` 和组层级。
- 保留 TanStack Table 原始构建方式，不引入 `TablePrimitives`、`TablePagination`、兼容层或包装表格组件。
- 强化权限目录层级、选中反馈、批量 `scope` 的动作含义和分页状态。
- 增加轻量顶部工具条，展示当前选择状态，并提供“仅看已选”开关。
- 保持现有无障碍契约、测试定位方式和防卡死稳定逻辑。

## 非目标

- 不把表格改成卡片列表、树控件或旧通用表格组件。
- 不新增搜索、清空选择、批量全选、展开全部、持久化筛选等额外功能。
- 不改变提交 payload、权限选择数据模型、审批人默认逻辑或后端 API。
- 不改变 TanStack Table 版本和项目级表格架构测试口径。
- 不为了视觉效果删除原生表格语义、表头或表单控件。

## 方案选择

已评估三种方向：

1. 审计控制台式权限篮：高密度、强选中反馈、保留横向核对能力。
2. 分组段落式目录：父子层级更像分段目录，但弱化表头对齐和横向比较。
3. 强操作型选择面板：选择动作更醒目，但密度下降，左栏空间压力更大。

最终采用方案 1，并吸收方案 2 的树形轨道和组上下文表达。这样可以保留权限申请所需的表格比较能力，同时解决现有层级和状态反馈不足的问题。

## 用户体验设计

### 顶部工具条

权限表格上方新增一个轻量工具条，作为表格的一部分呈现，不作为外层表单说明文本。

工具条展示：

- `已选 N 项`：统计当前直接权限选择数量。多 `scope` 权限按已选 `scope` 数计入，与现有 `selectedPermissionKeys.length` 口径一致。
- `scope 已设置 N 项`：统计当前 `selectedScopes` 中非空值数量。
- `当前显示 X/Y`：显示过滤后的可见行数与总行数。未开启“仅看已选”时，`X` 等于分页前总行数；开启后，`X` 等于已选过滤后的行数。
- “仅看已选”开关：只影响当前表格展示，不改变选择结果、展开状态或提交数据。

工具条不提供“清空选择”。清空属于破坏性批量操作，当前需求只需要核对体验。

### 表格层级

首列继续作为 sticky 列，并承担目录树表达：

- 权限组行使用明确的展开图标、组名、选中计数徽标和层级轨道。
- 权限项行使用缩进、轻量叶子标识和纵向连接线，避免当前孤立圆点造成的弱层级感。
- 已选权限行增加左侧强调条和柔和背景。
- 权限组在部分或全部子权限被选中时，计数徽标高亮；半选 checkbox 仍由 DOM `indeterminate` 属性表达。

整行点击权限组仍用于展开或收起。键盘路径继续依赖组名按钮和表单控件，不把 `<tr>` 改成伪按钮。

### `scope` 区域

单 `scope` 或无 `scope` 权限继续使用原有 `select` 交互，保留可访问名称 `{permission.key} scope`。

权限组批量 `scope` 仍使用 `select`，但视觉上表达为“应用到子权限”的动作型控件：

- 默认文案保留批量含义，例如“批量应用 scope”。
- 选择后立即调用现有 `onPermissionGroupScopeChange`。
- 控件本身不显示为持久筛选值，避免误导用户以为这是组的固定状态。

多 `scope` 权限继续在 `scope` 列内显示多个 checkbox，保留可访问名称 `选择 {permission.key} {scope.key}`。选择列不再只以普通横杠呈现，而应显示“按 scope 选择”这类非交互状态标识，明确选择入口在 `scope` 区域。

### 选择区域

选择列继续保留 checkbox：

- 权限组 checkbox 保留 `选择权限组 {group.key}`。
- 单 `scope` 权限 checkbox 保留 `选择 {permission.key}`。
- 多 `scope` 权限选择列显示非交互标识，保留 `aria-label="{permission.key} 多 scope 选择"`。

所有 checkbox 和 select 点击仍必须 `stopPropagation`，避免触发权限组行的展开或收起。

### 分页区

分页区重构为精致状态条，但保持原有 TanStack pagination 能力：

- 保留 `每页条目数` select。
- 保留 `上一页` 与 `下一页` icon button。
- 显示当前页范围，例如 `第 1-5 条 / 共 18 条`。
- “仅看已选”开启时，分页基于过滤后的 rows。

后续实现不调整“父子行可能跨页”的根本行为。该问题存在于扁平 row model 与分页组合中，但本次只做视觉与轻量过滤，不改分页模型，避免扩大风险。

## 组件与代码边界

主要修改范围预计为：

- `frontend/src/pages/portal/components/PermissionSelector.tsx`
- `frontend/src/styles/features/permission-selector.css`
- `frontend/src/pages/portal/PortalPage.test.tsx`
- `frontend/src/components/tableArchitecture.test.ts`

`PermissionSelector.tsx` 继续保留：

- `useReactTable`
- `getCoreRowModel`
- `getPaginationRowModel`
- 原生 `<table aria-label="权限选择">`
- `flexRender`
- `getRowId`
- `useExitingGroupKeys` 的 memo 化返回和等值 state guard

不得引入：

- `components/ui/TablePrimitives`
- `components/ui/TablePagination`
- `DataTable` 或任何自建表格封装
- 兼容旧表格 class 的样式层

工具条和样式辅助函数可以作为 `PermissionSelector.tsx` 内部局部组件实现。除非文件复杂度明显失控，不新增跨页面通用组件。

## 数据流

新增“仅看已选”本地状态：

- 状态只存在于 `PermissionSelector` 内部。
- 开启后，用当前 `selectedKeys` 和权限组选择状态过滤 rows。
- 权限项命中条件：该权限的任意 selection key 已选中。
- 权限组命中条件：该组 `selectionState` 为 `checked` 或 `indeterminate`，或存在已选后代权限。
- 过滤后再传给 TanStack Table，确保 pagination 和显示计数同源。
- 切换“仅看已选”或 page size 时，页码回到第一页，避免出现空页。

`scope 已设置 N 项` 直接从 `selectedScopes` 的非空值统计，不推导不存在的默认值。

## 错误与空状态

保持现有加载和错误状态：

- 未选择应用：展示“选择应用后加载权限目录”。
- 加载中：展示“权限目录加载中”。
- 加载失败：展示“权限目录加载失败”。

当应用存在但无直接权限 rows 时，不继续返回 `null`。后续实现应在“直接权限”区域展示明确空状态：当前应用未返回可直接申请的权限，可仅选择权限组发起申请。这样避免表单区域突然消失。

“仅看已选”开启后如果没有命中 rows，应展示表格内空状态，说明当前没有已选直接权限，并允许用户关闭开关继续浏览。

## 无障碍契约

实现必须保持以下契约：

- 表格 role 仍为原生 `table`，名称为“权限选择”。
- 表头仍包含“权限”“权限 key”“scope”“选择”。
- 权限组展开按钮保持 `aria-expanded`，可访问名称形如“展开 订单”“收起 订单”。
- 权限组选择 checkbox 保持 `选择权限组 {group.key}`。
- 单 `scope` 权限 checkbox 保持 `选择 {permission.key}`。
- 多 `scope` 权限 checkbox 保持 `选择 {permission.key} {scope.key}`。
- 权限 `scope` select 保持 `{permission.key} scope`。
- 权限组批量 `scope` select 保持 `{group.key} 权限组 scope`。
- 分页控件保持 `每页条目数`、`上一页`、`下一页`。
- 父级 checkbox 半选状态继续写入 `HTMLInputElement.indeterminate`。
- 降低动效偏好下，展开或收拢动画必须停用。

## 测试设计

需要保留并扩展现有测试。

`PortalPage.test.tsx` 建议新增或调整：

- 断言表格表头仍可通过 role/name 访问。
- 断言展开按钮的 `aria-expanded` 从 `false` 到 `true` 再回到 `false`。
- 断言 checkbox 点击不会冒泡触发权限组展开或收起。
- 断言多 `scope` 权限选择列显示“按 scope 选择”语义，并保持 `aria-label="{permission.key} 多 scope 选择"`。
- 覆盖“仅看已选”：开启后只显示已选权限及相关权限组，关闭后恢复完整 rows。
- 覆盖“仅看已选”无结果空状态。
- 覆盖分页状态在过滤后使用过滤后的总数。

`tableArchitecture.test.ts` 继续保证：

- `PermissionSelector.tsx` 不引用 `TablePrimitives` 或 `TablePagination`。
- `PermissionSelector.tsx` 保留 `useReactTable` 和原生 `<table>`。
- `useExitingGroupKeys` 继续 memo 化返回值，`setExitingGroupKeys` 继续使用 `stringListsAreEqual(current, next) ? current : next`。

最小验证命令：

```bash
pnpm --dir frontend test frontend/src/pages/portal/PortalPage.test.tsx frontend/src/components/tableArchitecture.test.ts
pnpm --dir frontend typecheck
pnpm --dir frontend build
.venv/bin/python manage.py check
```

实现阶段如果修改 React build 产物或影响 Django 运行页面响应，还必须重启 Django 开发服务，并用 `/portal/request` 的真实 HTTP 响应或浏览器页面验证新代码已加载。

## 验收标准

- 权限选择表格呈现为现代、克制、高密度的权限核对面板。
- 已选权限、组内选中计数、`scope` 设置状态和当前显示范围在视觉上清楚可见。
- “仅看已选”只影响展示，不影响选择结果、展开状态、提交 payload 或后端契约。
- 多 `scope` 权限不会再被视觉误读为不可选择。
- 所有现有门户权限选择测试继续通过。
- 新增测试覆盖顶部工具条、过滤、表头语义、checkbox 冒泡边界和多 `scope` 视觉语义。
- 架构测试确认没有回到旧表格组件或新增表格包装层。

## 自审结论

本规格聚焦于门户申请权限表格的视觉与轻量交互重构，未包含后端 API、数据模型或跨页面表格系统改造。范围足够小，可以进入后续实施计划；当前没有未决项、没有兼容层要求、没有与现有 TanStack 原始构建约束冲突的设计。
