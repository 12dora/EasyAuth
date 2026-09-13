import { type ComponentPropsWithoutRef, type MouseEvent, type ReactNode } from "react";

import { useI18n } from "../../../i18n/I18nProvider";
import { Button } from "../../Button";
import { ButtonLink } from "../../ButtonLink";
import type { ColumnType } from "../AppTable";

/**
 * 操作列默认宽度: 三个两字 `size="sm"` 按钮(47px)+ 两道 6px 间距 + 单元格左右内边距(12+12)。
 * `tableLayout: "fixed"` 下列宽只能来自 `<colgroup>`, 所以操作列必须有一个真实宽度,
 * 不能再靠「收缩到内容」。
 */
export const ACTIONS_COLUMN_DEFAULT_WIDTH = 180;

export interface ActionsColumnConfig<T> {
  render: (record: T, index: number) => ReactNode;
  title?: ReactNode;
  /**
   * 列宽; 默认 `ACTIONS_COLUMN_DEFAULT_WIDTH`(够放三个两字按钮)。
   *
   * AppTable 固定用 `tableLayout: "fixed"`, 列宽只认 `<colgroup>`,
   * 旧的 `width: 1` + `w-0`(auto 布局下的「收缩到内容」写法)在 fixed 布局里
   * 会被原样当成 1px, 于是操作按钮整列溢出到相邻单元格上。
   * 按钮多于三个(或标签更长)时页面显式传实际宽度。
   */
  width?: number;
  /** 默认固定在右侧; 需要 AppTable 传 minWidth 才会生效。 */
  fixed?: ColumnType<T>["fixed"];
  key?: string;
}

/**
 * 操作列: 右对齐、不换行、固定右侧, 内部按钮点击不冒泡到行点击。
 * 按钮本身用 `RowActionButton` / `RowActionLink`(见下), 页面里不要再写
 * 裸的 `<Button size="sm" ...>` / `<ButtonLink size="sm" ...>`。
 */
export function actionsColumn<T>({
  fixed = "right",
  key = "actions",
  render,
  title,
  width = ACTIONS_COLUMN_DEFAULT_WIDTH,
}: ActionsColumnConfig<T>): ColumnType<T> {
  return {
    key,
    title: title ?? <ActionsColumnTitle />,
    fixed,
    width,
    align: "right",
    className: "whitespace-nowrap",
    render: (_value: unknown, record: T, index: number) => (
      <div className="flex items-center justify-end gap-1.5" onClick={stopRowClick} onDoubleClick={stopRowClick}>
        {render(record, index)}
      </div>
    ),
  };
}

function ActionsColumnTitle() {
  const { t } = useI18n();
  return <>{t("common.actions")}</>;
}

function stopRowClick(event: MouseEvent<HTMLElement>) {
  event.stopPropagation();
}

/** 行内操作按钮支持的两种语气: 普通与破坏性。 */
export type RowActionVariant = "ghost" | "ghost-danger";

/**
 * 表格行内操作按钮: 仓库自研 Button 的 `size="sm"`(h-7, 与分页控件的 28px 对齐)预设。
 *
 * 「点击不冒泡到行」由 actionsColumn 的容器负责, 所以这里只固定尺寸与语气;
 * 工作区四个页签包、矩阵、目录面板都用它, 页面里不要再各写一份。
 */
export function RowActionButton({
  variant = "ghost",
  ...props
}: Omit<ComponentPropsWithoutRef<typeof Button>, "size" | "variant"> & { variant?: RowActionVariant }) {
  return <Button size="sm" variant={variant} {...props} />;
}

/**
 * 表格行内操作链接: `RowActionButton` 的 `<a>` 版本(`components/ButtonLink` 的
 * `size="sm"` 预设)。「进入 / 查看 / 继续」这类跳转必须是真链接, 才能中键新开、
 * 复制地址、被爬到; 但它和同一格里的按钮共用 h-7 的尺寸与 ghost 语气。
 *
 * `href` + `onClick(preventDefault)` 的路由内跳转与 `to` 的 `<Link>` 两种写法
 * ButtonLink 都支持, 这里原样透传, 只锁死 size 与 variant 的取值域。
 */
export function RowActionLink({
  variant = "ghost",
  ...props
}: Omit<ComponentPropsWithoutRef<typeof ButtonLink>, "size" | "variant"> & { variant?: RowActionVariant }) {
  return <ButtonLink size="sm" variant={variant} {...props} />;
}
