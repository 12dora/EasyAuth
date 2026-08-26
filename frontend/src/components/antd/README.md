# `components/antd` — 数据表格地基

全站数据表格统一走 Ant Design `Table`，页面**只允许**消费本目录导出的封装。
`src/components/tableArchitecture.antd.test.ts` 是护栏：页面里直接 `import { Table } from "antd"`、
手写 `<table>`、用 `useReactTable`、或引入自研表格原语（`components/ui/TableView` 等）都会让测试失败。
未迁移的页面登记在该测试的 `ALLOWED_LEGACY_TABLE_FILES` 里，迁一个删一行。

主题与 locale 由 `AppConfigProvider` 在 `src/main.tsx` 里全局挂载（在 `I18nProvider` 之内），
页面不需要再包 `ConfigProvider`。

---

## `AppTable<T>` — `./AppTable`

```ts
<AppTable<Row>
  columns={ColumnsType<Row>}
  dataSource={Row[]}
  rowKey="id"                    // 必填
  loading?={boolean}
  minWidth?={number | "max-content"}
  sticky?={boolean | { offsetHeader?: number }}
  pagination?={TablePaginationConfig | false}
  emptyTitle?={string} emptyDescription?={string} emptyIcon?={ReactNode} emptyAction?={ReactNode}
  empty?={ReactNode}             // 完全自定义空态, 覆盖上面四个
  onRow? onChange? ...           // 其余 antd TableProps 原样透传
/>
```

AppTable 独占的布局约定（**页面不要重复传**）：

| 约定 | 值 |
| --- | --- |
| 宽度 | 包裹层 `w-full` |
| 尺寸 | `size="middle"`（可覆盖） |
| 布局 | `tableLayout="fixed"` |
| 行高 / 单元格内边距 | 主题 `Table` token（`cellPaddingBlockMD: 10`、`cellPaddingInlineMD: 12`），等于旧 `TABLE_CELL_CLASS` 的 `px-3 py-2.5` |
| 横向滚动 | 只有传 `minWidth` 才写 `scroll.x`；不传则随容器收缩 |
| 空态 | 复用 `components/ui/EmptyState`，默认标题 `table.empty.title` |
| 加载态 | 透传 `loading`，用 antd 自带 Spin |
| 分页 | `position: ["bottomRight"]`、`size="small"`、`showSizeChanger`、`pageSizeOptions [10,20,50,100]`、`defaultPageSize 10`、`showTotal` = `第 x-y 条 / 共 z 条`；全部渲染在同一个 `ul.ant-pagination` 里 |

用 `actionsColumn`（固定右列）时**必须**同时传 `minWidth`，否则 antd 无法固定列。

常量：`APP_TABLE_PAGE_SIZE_OPTIONS`、`APP_TABLE_DEFAULT_PAGE_SIZE`。
类型再导出：`ColumnsType`、`ColumnType`、`ColumnGroupType`、`TableProps`、`TablePaginationConfig`。

## 列预设 — `./columns`

所有预设都是泛型的，`title` 由调用方传**已本地化**的节点；预设自带的文案走 `table.*` i18n。

```ts
statusColumn<T>({ key, title, options, getValue?, width?, filter? = true }): ColumnType<T>
// options: { value: string; label: ReactNode; tone?: BadgeTone }[]
// 渲染 <Badge tone>；内建 enumFilter；未知值按 neutral 原样显示；空值 "-"

dateTimeColumn<T>({ key, title, getValue?, width? = 170, sorter? = true }): ColumnType<T>
// 走 useI18n().formatDateTime(跟随界面语言)；sorter 按时间戳比较

textColumn<T>({ key, title, getValue?, filter? = false, sorter? = false,
                ellipsis? = true, mono? = false, width? }): ColumnType<T>
// filter -> textFilter 子串筛选；sorter -> localeCompare；mono -> 等宽 code 展示；空值 "-"

userColumn<T>({ getName, getUserId?, key? = "user", title?, filter? = false, width? }): ColumnType<T>
// 显示名(粗体) + 等宽 user id 两行, 沿用 ConsoleTeamMemberTable 的成员单元格排版
// 仓库里没有表格内头像的先例, 因此不渲染头像

actionsColumn<T>({ render, title?, width? = 1, fixed? = "right", key? = "actions" }): ColumnType<T>
// render: (record, index) => ReactNode, 右对齐 / 不换行 / 点击不冒泡到行
// 按钮继续用 components/ui/TableActions 的 TableRowActionButton / TableRowActionLink
```

## 筛选助手 — `./AppTable`

```ts
textFilter<T>(columnKey: string, options?: {
  getValue?: (record: T) => string | null | undefined;   // 默认 record[columnKey]
  placeholder?: string;
}): { filterDropdown; onFilter }
// antd 没有内建文本筛选: 输入框 + 确定/重置, 大小写不敏感的子串匹配, 空关键字=不筛选

enumFilter<T>(columnKey: string, options: { label: ReactNode; value: string }[], config?: {
  getValue?: (record: T) => string | string[] | null | undefined;
}): { filters; onFilter }
// antd 内建复选下拉 + 精确匹配; getValue 返回数组时按「包含」匹配
```

两者都直接展开到列定义上，列必须有 `key`（或 `dataIndex`），否则 antd 无法回传筛选状态：

```tsx
{ title: t("common.name"), dataIndex: "name", key: "name", ...textFilter<Row>("name") }
```

## 服务端分页 — `useServerTable`

分页状态、页长选项、「筛选/排序后回到第 1 页」、antd `onChange` → 后端查询参数，
**只在这里**实现，页面不要自己再写一遍。

```ts
const serverTable = useServerTable<Row>({
  total: data?.pagination.total_items,          // 后端总条数
  defaultPageSize?: 10,
  defaultSort?: { field: "updated_at", order: "descend" },
  filterParams?: { status: "status", appKey: "app_key", name: { param: "q" } },
  sortParam?: "ordering",                       // 默认 DRF 风格, 降序前缀 "-"
  serializeSort?: (sort) => ({ ... }),          // 需要别的拼法时覆盖
});

serverTable.params      // { page, page_size, ...映射后的筛选, [ordering] } 直接拼请求
serverTable.query       // { page, pageSize, sortField, sortOrder, filters } 原始状态
serverTable.tableProps  // { pagination: { current, pageSize, total }, onChange }
serverTable.setPage(page, pageSize?)
serverTable.reset()

<AppTable<Row> {...serverTable.tableProps} columns={columns} dataSource={rows}
               loading={isLoading} rowKey="id" />
```

`filterParams` 的值可以是字符串（等价 `{ param }`）或
`{ param, multiple?: boolean, serialize?: (values: string[]) => string | string[] | undefined }`。
默认只取第一个选中值；`multiple: true` 保留数组。未声明的列筛选不会进 `params`，但仍在 `query.filters` 里。

同名导出的 `filtersToParams(filters, map)` 可在需要手工拼参数时单独使用。

## 主题 — `./theme` / `./AppConfigProvider`

`APP_ANTD_THEME` 把 `src/styles/index.css` 的 `:root` 设计令牌映射成 antd token
（详见 `docs/operations/frontend-build-budget.md` 与 theme.ts 的注释）。
antd 需要可解析的具体色值来派生 hover/active 色阶，所以那里是十六进制字面量，
**改 index.css 的令牌必须同步改 theme.ts**。控件高度与 `components/Button.tsx` 对齐：
`controlHeightSM 28 / controlHeight 36 / controlHeightLG 44`。

`AppConfigProvider` 还做两件事：`locale` 跟随 `I18nProvider`（zhCN ↔ enUS），
`button.autoInsertSpace: false`（否则 antd 会把两个汉字渲染成「确 定」）。

应用没有深色主题，因此不配置 `theme.algorithm`；将来接入时在 `theme.ts` 里加 `algorithm`。

## 已知注意点

- **不引入 `antd/dist/reset.css`**：antd v5 默认 CSS-in-JS，Tailwind preflight 已完成
  `box-sizing`/list/margin 重置，再叠一层 antd reset 会互相覆盖。
- **antd 的样式不在 Tailwind 的 `@layer` 里**，因此优先级高于 Tailwind 工具类。
  给 antd 组件加工具类覆盖样式时，要么用 `!` 重要性变体，要么改主题 token。
