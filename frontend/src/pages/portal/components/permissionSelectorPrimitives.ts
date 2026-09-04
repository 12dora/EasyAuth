/**
 * 权限选择表格的视觉规格。
 *
 * 全站数据表格已统一到 components/antd/AppTable, 只有这张表按架构约定继续用
 * TanStack + 原生表格元素(行内有可展开的权限组与下拉, antd Table 撑不住),
 * 因此原来的 components/ui/tableStyles 只剩它一个消费方, 直接搬到它旁边,
 * 地基目录里不再留一份没人用的表格原语。
 */
/*
 * `w-full` 让表格铺满滚动容器(否则列宽之和小于容器时表格右边会空出一条),
 * `min-w-[48rem]` 保留下限: 容器更窄时表格不再压缩, 由外层横向滚动接管。
 */
export const TABLE_ROOT_CLASS = "w-full min-w-[48rem] border-separate border-spacing-0 text-body";

/*
 * 表头底色必须不透明: 表头粘在滚动容器顶部(见 PermissionSelectorTable),
 * 半透明底色会把从它底下滚过去的权限行透上来叠成两层字。
 * 取值与 permission-selector.css 里粘住的权限列表头(--paper-deep)同一个口径。
 */
export const TABLE_HEAD_CLASS = "bg-paper-deep";

export const TABLE_ROW_CLASS = "group transition-colors hover:bg-accent/5";

export const TABLE_HEADER_CELL_CLASS =
  "whitespace-nowrap border-b border-ink/15 px-3 py-2.5 text-left align-bottom font-mono text-micro uppercase tracking-caps-wide text-ink-soft font-medium";

export const TABLE_CELL_CLASS = "border-b border-ink/8 px-3 py-2.5 text-body text-ink align-middle";
