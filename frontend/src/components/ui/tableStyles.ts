// 表格视觉规格的唯一出处。TablePrimitives 与门户权限选择表格
// (按架构约定直接渲染原生 table)都从这里取 class,避免两处字面量漂移。
export const MONO_TEXT_CLASS = "font-mono text-body leading-5 text-ink-soft";

export const TABLE_ROOT_CLASS = "min-w-full border-separate border-spacing-0 text-body";

export const TABLE_HEAD_CLASS = "bg-paper-deep/60";

export const TABLE_ROW_CLASS = "group transition-colors hover:bg-accent/5";

export const TABLE_HEADER_CELL_CLASS =
  "border-b border-ink/15 px-3 py-2.5 text-left align-bottom font-mono text-micro uppercase tracking-caps-wide text-ink-soft font-medium";

export const TABLE_CELL_CLASS = "border-b border-ink/8 px-3 py-2.5 text-body text-ink align-middle";
