# `components/antd` — 数据表格地基

全站数据表格统一走 Ant Design `Table`，页面**只允许**消费本目录导出的封装。
`src/components/tableArchitecture.antd.test.ts` 是护栏：页面里直接 `import { Table } from "antd"`、
手写 `<table>`、用 `useReactTable`、或引入自研表格原语都会让测试失败。
未迁移的页面登记在该测试的 `ALLOWED_LEGACY_TABLE_FILES` 里，迁一个删一行；
现在只剩门户 `PermissionSelector` 一族（TanStack + 原生 table，定高滚动不分页，按设计保留），
`components/ui/Table*` 自研原语已整体删除，它需要的表格 class 搬到了
`pages/portal/components/permissionSelectorPrimitives.ts`。

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
  ariaLabel?={string}            // 视觉隐藏的 <caption>, 即表格的可及名称
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
| 横向滚动 | `scroll.x` 恒有值：页面传的 `scroll.x` > `minWidth` > `"max-content"`；**空表例外**：无数据时 `minWidth` 让位给 `scroll.x: true`，否则表头按 minWidth 撑宽而空状态盒只有容器宽，两者错位 |
| 空态 | 复用 `components/ui/EmptyState`，默认标题 `table.empty.title` |
| 加载态 | 透传 `loading`，用 antd 自带 Spin |
| 分页 | `position: ["bottomRight"]`、`size="small"`、`showSizeChanger`、`pageSizeOptions [10,20,50,100]`、`defaultPageSize 10`、`showTotal` = `第 x-y 条 / 共 z 条`；全部渲染在同一个 `ul.ant-pagination` 里，且**真的只有一行**（见下） |
| 可及名称 | `ariaLabel` -> 视觉隐藏的原生 `<caption>` |

用 `actionsColumn`（固定右列）时**必须**同时传 `minWidth`，否则 antd 无法固定列。

### 单行分页与 `.ant-pagination`

antd 给 `.ant-pagination` 写死 `flex-wrap: wrap`，容器一窄「共 x 条 / 页码 / 每页条数」
就会折成两三行。AppTable 统一给分页挂 `APP_TABLE_PAGINATION_CLASS`
（`app-table-pagination`），规则在 `src/styles/features/app-table.css`：
`flex-wrap: nowrap` + 子项 `flex: none` + 分页条自身 `overflow-x: auto`
（放不下时是分页条横向滚动，而不是换行或把文案挤成两行）。
class 名与选择器必须成对存在，`AppTable.test.tsx` 会把那张样式表读进 jsdom，
用 `getComputedStyle` 断言规则真的命中了元素。

同一份样式表还负责隐藏 `.ant-table-caption`：用「视觉隐藏」（`position: absolute` +
`clip-path`）而不是 `display: none`，否则 `ariaLabel` 的名字会一起从无障碍树里消失。

### 表格的可及名称 `ariaLabel`

一个页面上有多张结构相近的表（门户的授权 / 申请 / 审批）时，屏幕阅读器只会念
"table"，用户无从分辨。`ariaLabel` 走 antd/rc-table 的 `caption` 属性渲染成原生
`<caption>`——那是 HTML 给表格命名的方式，直接成为 `role="table"` 的可及名称，
不需要额外的 `aria-label` 或包一层 `role="region"`。文案照常走 i18n
（门户三张表是 `portal.grants.ariaLabel` / `portal.requests.ariaLabel` /
`portal.approvals.ariaLabel`）。

### 为什么 `scroll.x` 永远有值

`scroll.x` 一身两职：它既是 antd 给 `.ant-table-content` 挂 `overflow-x: auto` 的开关，
也是 fixed 布局下表格宽度的来源。不设它的表格一旦列宽之和超过容器，
**会把整页撑出横向滚动条**（`visual-alignment.spec.ts` 的
`expectTablesUseLocalHorizontalScroll` 就是拦这个的）；而且 fixed 布局下没有剩余宽度时，
不写 `width` 的列会被压到 0px，整列文字消失。

所以缺省回落到 `"max-content"`：列按内容取宽，表格自身仍带 antd 写死的 `min-width: 100%`，
宽屏下照常铺满容器。**新表格一律要传 `minWidth` 像素数**，`"max-content"` 只是
「没人声明」时的安全兜底，代价有两条：`ellipsis` 列不再截断（内容多宽列就多宽），
表格也可能比卡片宽（门户授权表实测 1249px 挤在 960px 的卡片里）。

取值口径：**所有定宽列的 `width` 之和 + 每个不定宽列约 240**。
算出来比卡片窄时，`table { min-width: 100% }` 会把表格拉满，多出来的宽度落在
不定宽列上——也就是「桌面端刚好铺满、窄屏才局部横向滚动」。
（换行展示的列，即 `ellipsis: false`，按 180 估更贴近实际。）

常量：`APP_TABLE_PAGE_SIZE_OPTIONS`、`APP_TABLE_DEFAULT_PAGE_SIZE`。
类型再导出：`ColumnsType`、`ColumnType`、`ColumnGroupType`、`TableProps`、`TablePaginationConfig`、
`FilterDropdownProps`、`FilterValue`、`SortOrder`、`SorterResult`、`TableCurrentDataSource`。
写自定义 `filterDropdown` 或 `onChange` 的签名时从这里取，**页面不要 import `antd/es/table/*`**
（那是 antd 内部路径，迁移护栏 `FORBIDDEN_ANTD_TABLE_IMPORT` 也拦着）。

`showTotal` 的区间不看当前页实际渲染了几行，而是 antd 按分页配置推出来的：
`[(current - 1) * pageSize + 1, min(current * pageSize, total)]`——服务端分页下就是
`page` / `page_size`，所以最后一页只剩 3 行也会正确显示 `第 41-43 条 / 共 43 条`。
`total` 为 0 时 antd 回落到 `dataSource.length`（`setTotal` 还没回填的第一帧就是这样）。

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

actionsColumn<T>({ render, title?, width? = ACTIONS_COLUMN_DEFAULT_WIDTH, fixed? = "right", key? = "actions" }): ColumnType<T>
// render: (record, index) => ReactNode, 右对齐 / 不换行 / 点击不冒泡到行
// ACTIONS_COLUMN_DEFAULT_WIDTH = 180: 三个两字 size="sm" 按钮 + 间距 + 单元格内边距。
// tableLayout: "fixed" 下列宽只认 <colgroup>, 没有「收缩到内容」这回事 ——
// 按钮更多或标签更长时(如应用列表的四个按钮)页面必须显式传实际宽度, 否则整列会溢出到邻格上。

serverColumn<T>(column, filteredValue?, { multiple? = false }): ColumnType<T>
// 把任意列改造成「服务端筛选」列: 去掉 onFilter + 受控 filteredValue(见下)

serverSortColumn<T>(column, sort: ServerSortState): ColumnType<T>
// 把任意列改造成「服务端排序」列: sorter: true(不带比较函数) + 受控 sortOrder(见下)
```

`dateTimeColumn` 默认自带时间戳比较函数、`textColumn({ sorter: true })` 默认按
localeCompare 比较 —— **这两个默认值只在客户端表格上成立**。服务端分页表上一律
过 `serverSortColumn`(它会覆盖掉传进来的比较函数); 后端排不了的列干脆不给 sorter。

操作列里的按钮/链接只能用本目录的这两个预设(分别是仓库自研 `components/Button`
与 `components/ButtonLink` 的 `size="sm"` 版本):

```tsx
actionsColumn<Row>({
  render: (row) => (
    <>
      <RowActionButton type="button" onClick={...}>{t("common.edit")}</RowActionButton>
      <RowActionButton type="button" variant="ghost-danger" onClick={...}>{t("common.delete")}</RowActionButton>
      <RowActionLink href={`/console/apps/${row.app_key}`} icon={<ArrowRight size={15} />} onClick={...}>
        {t("common.enter")}
      </RowActionLink>
    </>
  ),
})
```

`size="sm"`(h-7)与分页控件的 28px 对齐; 破坏性动作用 `variant="ghost-danger"`
(两者的 `variant` 都只收 `ghost` / `ghost-danger`, 默认 `ghost`)。
「进入 / 查看 / 继续」这类跳转要用 `RowActionLink` 而不是按钮 —— 它渲染真正的
`<a>`, 可以中键新开、复制地址; `to`(react-router `<Link>`)与
`href` + `onClick(preventDefault)` 两种写法都原样透传给 `ButtonLink`。
「点击不冒泡到行」由 `actionsColumn` 的容器负责, 两者都不用再管。

**页面里不要再写裸的 `<Button size="sm" variant="ghost">` / `<ButtonLink size="sm">`**,
也不要在页面里包一层自己的 RowAction* —— 全站只有这一份。

同目录还导出 `MONO_TEXT_CLASS`: 表格内等宽标识符(app_key / user_id / 版本号)的唯一 class 出处。

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

```ts
dateRangeFilter<T>(paramKey? = "created", options?: {
  inputType?: "datetime-local" | "date";      // 默认 datetime-local
  fromLabel?: string; toLabel?: string;       // 默认 `<paramKey>_from` / `<paramKey>_to`
}): { filterDropdown; decode; encode; toParams }
// antd 只内建「文本 / 枚举」两种筛选, 时间范围要自定义下拉:
// 两个时间输入 + 确定/重置, 起止编码进同一个筛选值("<from>~<to>"), 一列只占一个筛选槽。
// toParams(from, to) -> { <paramKey>_from, <paramKey>_to }, 空的一端不进参数;
// encode({from,to}) / decode(values) 用来在 URL <-> 受控 filteredValue 之间来回。
```

三者都直接展开到列定义上，列必须有 `key`（或 `dataIndex`），否则 antd 无法回传筛选状态：

```tsx
{ title: t("common.name"), dataIndex: "name", key: "name", ...textFilter<Row>("name") }
```

`encodeDateRange` / `decodeDateRange` 也单独导出，URL 驱动的页面用它们把
`created_from` / `created_to` 拼成受控筛选值。

## 服务端筛选的列 — `serverColumn`

**只要筛选发生在后端，列就必须过一遍 `serverColumn`**，否则会静默丢数据：

```tsx
serverColumn(
  textColumn<AuditRow>({ key: "app", title: t("common.app"), getValue: auditAppKey, filter: true }),
  filters.app,                                  // 来自 URL / 查询状态, 未筛选传 undefined
)
```

它做两件事，少一件都出错：

1. **去掉列预设自带的 `onFilter`**：antd 在受控筛选（传了 `filteredValue`）下**依然**会执行
   `onFilter`，于是后端已经筛过的当前页被客户端再筛一遍。审计行的 `app_key` 藏在
   `metadata` 里、列上读不到，再筛一次会把整页筛空。`AppTable.test.tsx` 里有一条用例
   专门锁住这个行为（不加 `serverColumn` 就会掉行）。
2. **用 `filteredValue` 受控**：筛选值的真相在 URL / 查询状态里，`null` 表示未筛选；
   交给 antd 内部状态会让刷新、深链后的表头图标与实际请求参数对不上。

`{ multiple: true }` 才允许内建枚举下拉多选（默认单选，因为 `filtersToParams`
默认只取第一个值，多选会被静默丢掉）；自定义下拉（文本 / 时间范围）不受这个开关影响。

时间范围列的完整写法：

```tsx
const submitted = dateRangeFilter<Row>("submitted");
const column = serverColumn(
  { ...dateTimeColumn<Row>({ key: "submitted_at", title: t("..."), sorter: false }), ...submitted },
  submitted.encode({ from, to }),
);
// 请求参数: { ...serverTable.params, ...submitted.toParams(from, to) }
```

## 服务端排序的列 — `serverSortColumn`

**只要排序发生在后端, 列就必须过 `serverSortColumn`**, 否则表头会撒谎:

```tsx
serverSortColumn(
  dateTimeColumn<Row>({ key: "created_at", title: t("...") }),
  sort,                                          // = useServerTable().query
)
```

它做两件事, 少一件都出错:

1. **`sorter: true`, 不带比较函数**。列预设自带的客户端比较函数只对「当前页那几行」
   生效: 表头写着按时间倒序, 实际只是把第 2 页内部重排了一遍, 与分页条的「共 N 条」
   自相矛盾。传进来的列若还带着比较函数, `serverSortColumn` 会覆盖掉。
2. **`sortOrder` 受控**。排序的真相在 `useServerTable().query` 里(它就是 `ordering`
   参数的来源), 交给 antd 内部状态会让表头指示器和实际请求参数对不上; 而且别的列
   排序时本列必须显式回到 `null`, 否则会同时亮起两个指示器。

后端**排不了**的列一律不给 sorter(而不是留一个只作用于当前页的客户端排序):
应用列表的负责人、交接单的负责人与阻塞、审批实例的业务单号、清单版本的导入人……

各页的「列 key -> 后端公开字段名」映射表就写在对应的 hook 里(常量名 `*_ORDERING_FIELDS`),
和建表的 `useServerTable(...)` 挨着, 改后端允许的排序字段时一处就能对齐。

## 服务端分页 — `useServerTable`

分页状态、页长选项、「筛选/排序后回到第 1 页」、antd `onChange` → 后端查询参数，
**只在这里**实现，页面不要自己再写一遍。

```ts
const serverTable = useServerTable<Row>({
  defaultPageSize?: 10,
  filterParams?: { status: "status", appKey: "app_key", name: { param: "q" } },
  sortParam?: ORDERING_PARAM,                   // "ordering"; DRF 风格, 降序前缀 "-"
  serializeSort?: orderingSerializer({ ... }),  // 列 key 与后端字段名不一致时(见下)
});

serverTable.params      // { page, page_size, ...映射后的筛选, [ordering] } 直接拼请求
serverTable.query       // { page, pageSize, sortField, sortOrder, filters } 原始状态
serverTable.tableProps  // { pagination: { current, pageSize, total }, onChange }
serverTable.total       // 当前生效的总条数
serverTable.setPage(page, pageSize?)
serverTable.setSort(sort | undefined)           // 直接改排序(并回到第 1 页), 见下
serverTable.setTotal(total)                     // 拿到响应后回填总条数, 见下
serverTable.reset()

const query = useQuery({ queryKey: [..., serverTableQuery(serverTable.params)], ... });
serverTable.setTotal(query.data?.pagination.total_items);

<AppTable<Row> {...serverTable.tableProps} columns={columns} dataSource={rows}
               loading={query.isLoading} rowKey="id" />
```

### 总条数 `setTotal`

总条数只有请求回来后才知道，而那次请求正是用 `serverTable.params` 发出去的，
所以**建 hook 时拿不到 total**（`total` 选项只适合总数来自另一个已完成查询的场景）。
拿到响应后调 `setTotal(n)`，总数就进了 `tableProps.pagination`，
页面不用再手工拼 `pagination={{ current, pageSize, total }}`。

- 可以直接写在渲染期（`serverTable.setTotal(data?.pagination.total_items)`）：
  内部先比值再 `setState`，值没变就不触发重渲染。**注意顺序不能反**——
  渲染期的 `setState` 不看新旧值是否相同，无条件调用会直接撞上 React 的 25 轮上限。
- 传 `undefined` / `null` 表示「这次还不知道」，保留上一次的总数，
  刷新数据时分页条不会闪一下 0。
- 只拿得到 `tableProps`、拿不到 hook 本体时（某个自定义 hook 只透出 tableProps），
  用纯函数版本 `tablePropsWithTotal(tableProps, total)`。
- `total` 选项仍然有效且优先级更高，老代码不用改。

### 排序参数映射 `orderingSerializer`

后端在所有服务端分页列表上统一收单字段的 `ordering=<field>` / `ordering=-<field>`
(非法字段 400)。列 key 与后端公开字段名并不总是同一个词, 所以每张表给一份小映射,
「asc/desc -> 有无 `-` 前缀」的拼法只在 `orderingSerializer` 里写一次:

```ts
const REQUEST_ORDERING_FIELDS = {
  submitted_at: "created_at",     // 列 key 是 payload 字段名, 后端排序字段叫 created_at
  status: "status",
  app: "app_key",
} as const;

useServerTable<Row>({
  sortParam: ORDERING_PARAM,
  serializeSort: orderingSerializer(REQUEST_ORDERING_FIELDS),
});
```

映射表里没有的列不产生排序参数(那种列本来就不该有 sorter)。

**表格一律不设默认排序**: 页面不要传 `defaultSort`(hook 上保留这个能力, 但没人用)。
首屏不发 `ordering`, 顺序由后端的默认序决定, 表头也就不带排序指示器 —— 全站首屏一致。
`ordering` 必须一起进查询串与查询键(`serverTableQuery(serverTable.params)`),
否则点了表头 react-query 命中旧缓存、不会重新请求。

### 排序随外部状态切换 `setSort`

「排序跟着别的状态变」的场景在切换时显式调 `setSort(...)`(它自带回到第 1 页),
传 `undefined` 表示清掉排序、把顺序交回后端默认序 —— 门户审批切换待办/已处理页签
就是这么做的。表头点击仍然只走 `onChange`。

### 筛选参数映射 `filterParams`

`filterParams` 的值可以是字符串（等价 `{ param }`）或
`{ param, multiple?: boolean, serialize?: (values: string[]) => string | string[] | undefined }`。
默认只取第一个选中值；`multiple: true` 保留数组。未声明的列筛选不会进 `params`，但仍在 `query.filters` 里。

同名导出的 `filtersToParams(filters, map)` 可在需要手工拼参数时单独使用。

### 参数拼串 `serverTableQuery`

```ts
serverTableQuery(serverTable.params, { app_key: "demo" })  // "page=1&page_size=10&app_key=demo"
```

空值不进串（与后端「不传即不过滤」的口径一致），数组按同名多值展开，
键顺序沿用参数对象的插入顺序，可以直接当查询缓存键用。

## 主题 — `./theme` / `./AppConfigProvider`

`APP_ANTD_THEME` 把 `src/styles/index.css` 的 `:root` 设计令牌映射成 antd token
（详见 `docs/operations/frontend-build-budget.md` 与 theme.ts 的注释）。
antd 需要可解析的具体色值来派生 hover/active 色阶，所以那里是十六进制字面量，
**改 index.css 的令牌必须同步改 theme.ts**。控件高度与 `components/Button.tsx` 对齐：
`controlHeightSM 28 / controlHeight 36 / controlHeightLG 44`。

`AppConfigProvider` 还做两件事：`locale` 跟随 `I18nProvider`（zhCN ↔ enUS），
`button.autoInsertSpace: false`（否则 antd 会把两个汉字渲染成「确 定」）。

应用没有深色主题，因此不配置 `theme.algorithm`；将来接入时在 `theme.ts` 里加 `algorithm`。

## 测试脚手架 — `./testing`

```ts
renderWithAntd(ui, options?)                  // = render(ui, { wrapper: AppTableTestProvider })
AppTableTestProvider                          // I18nProvider + AppConfigProvider
openHeaderFilter(user, columnTitle)           // 打开某列表头筛选下拉, 返回下拉面板
openHeaderFilter(user, scope, columnTitle)    // 一个页面有多张表时限定在某个容器内
openFilterDropdown()                          // 已经点开时, 等下拉可见并返回
sortByColumn(user, [scope,] columnTitle)      // 点一次某列表头的排序区
columnSortOrder([scope,] columnTitle)         // 该列亮着的排序指示器: ascend/descend/null
ANTD_TEST_TIMEOUT_MS                          // 30_000
```

- 渲染 AppTable 的用例**必须**包 `AppConfigProvider`（主题与 locale 都在那），
  而它自己要读 `I18nProvider` 的 locale，两层必须成对出现 —— 用 `renderWithAntd`
  就不用每个文件再抄一遍。
- antd Table 在 jsdom 里每次筛选/排序都要重建整棵表格，默认 5s 常常不够，
  在测试文件顶层写 `vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS })`。
- `sortByColumn` 点的是 `.ant-table-column-sorters` 而不是整个 `th`: 同时带筛选的列上
  点 `th` 可能命中筛选图标。`columnSortOrder` 读的是 antd 高亮的箭头, 因此服务端排序下
  它同时验证了「受控 `sortOrder` 真的回填到了表头」。
  注意 antd 的排序是三态循环(升 -> 降 -> 取消): 表格没有默认排序, 所以首屏点一列
  是升序、再点是降序、第三次才取消。
- `openHeaderFilter` 会等下拉真正可见（`.ant-dropdown:not(.ant-dropdown-hidden)`）再返回：
  antd 的下拉延迟挂载、收起时带动画，直接查 `.ant-table-filter-dropdown` 会拿到上一个。
  列名按「先前缀、后包含」匹配表头（固定列会让同一个标题在 DOM 里出现两次）。
- `testing.tsx` 依赖 `@testing-library`（devDependencies），**只能被测试文件引用**。
- 开了横向滚动的表格（现在是全部），rc-table 会在 `tbody` 里多渲染一行
  `tr.ant-table-measure-row` 量列宽，内容是整份表头的副本。它带 `aria-hidden`，
  `getByRole` 看不见，但 **`getByText` 会拿到两个**。断言列标题时限定在
  `thead.ant-table-thead` 内（`openHeaderFilter` 已经处理过这件事）。

## 类型报错 TS2742

自定义 hook 把 `tableProps` 透出去时，如果不写返回类型，tsc 会报
「The inferred type of ... cannot be named without a reference to `antd/es/table/interface`」。
给 hook 的返回值显式标注即可：

```ts
function useThings(): { rows: Row[]; tableProps: Pick<AppTableProps<Row>, "pagination" | "onChange"> } {
```

整只 hook 结果原样透出时用 `UseServerTableResult<Row>`。

## 已知注意点

- **不引入 `antd/dist/reset.css`**：antd v5 默认 CSS-in-JS，Tailwind preflight 已完成
  `box-sizing`/list/margin 重置，再叠一层 antd reset 会互相覆盖。
- **antd 的样式不在 Tailwind 的 `@layer` 里**，因此优先级高于 Tailwind 工具类。
  给 antd 组件加工具类覆盖样式时，要么用 `!` 重要性变体，要么改主题 token。
