/**
 * 权限选择表格的视觉规格。
 *
 * 全站数据表格已统一到 components/antd/AppTable, 只有这张表按架构约定继续用
 * TanStack + 原生表格元素(行内有可展开的权限组与下拉, antd Table 撑不住),
 * 因此原来的 components/ui/tableStyles 只剩它一个消费方, 直接搬到它旁边,
 * 地基目录里不再留一份没人用的表格原语。
 */
export const TABLE_ROOT_CLASS = "min-w-[48rem] border-separate border-spacing-0 text-body";

export const TABLE_HEAD_CLASS = "bg-paper-deep/60";

export const TABLE_ROW_CLASS = "group transition-colors hover:bg-accent/5";

export const TABLE_HEADER_CELL_CLASS =
  "whitespace-nowrap border-b border-ink/15 px-3 py-2.5 text-left align-bottom font-mono text-micro uppercase tracking-caps-wide text-ink-soft font-medium";

export const TABLE_CELL_CLASS = "border-b border-ink/8 px-3 py-2.5 text-body text-ink align-middle";
