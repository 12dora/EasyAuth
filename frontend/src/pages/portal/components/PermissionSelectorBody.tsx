import { flexRender, type Table } from "@tanstack/react-table";
import type { MouseEvent } from "react";

import { EmptyState } from "../../../components/ui/EmptyState";
import { cn } from "../../../lib/cn";
import { useI18n } from "../../../i18n/I18nProvider";

import { permissionSelectorTableMeta } from "./permissionSelectorMeta";
import { TABLE_CELL_CLASS, TABLE_ROW_CLASS } from "./permissionSelectorPrimitives";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

/*
 * 一次过渡里最多逐行做动画的行数。
 *
 * 进出场动画不是一条 opacity: 每行的每个单元格都在动 grid-template-rows(0fr <-> 1fr)
 * 以及单元格自身的上下内边距与下边框, 全都是要重新布局的属性。
 * 展开一两个权限组时这点代价看不出来, 但"展开全部"会让整份目录的行同时进场,
 * 浏览器要连着 160ms 每帧对上百行做整表重排, 表现就是点一下卡一下。
 * 超过这个阈值就整批跳过动画: 展开直接显示, 收起直接摘掉, 不留下一个"停 160ms 才消失"的空档。
 */
const ROW_MOTION_LIMIT = 40;

export function PermissionSelectorBody({ table }: { table: Table<PermissionSelectorRow> }) {
  const { t } = useI18n();
  const { disabled, showSelectedOnly, onToggleGroup } = permissionSelectorTableMeta(table);
  const rows = table.getRowModel().rows;
  const skipRowMotion = countMotionRows(rows) > ROW_MOTION_LIMIT;
  if (rows.length === 0) {
    return (
      <tbody>
        <tr className="group transition-colors hover:bg-transparent">
          <td
            colSpan={table.getAllLeafColumns().length}
            className={cn(TABLE_CELL_CLASS, "py-10 text-center text-ink-soft")}
          >
            <EmptyState
              title={showSelectedOnly ? t("selector.emptySelected.title") : t("selector.empty.title")}
              description={showSelectedOnly ? t("selector.emptySelected.description") : t("selector.empty.description")}
            />
          </td>
        </tr>
      </tbody>
    );
  }

  return (
    <tbody>
      {rows.map((row) => {
        // 跳过动画时退场行没有可播的动画, 直接不渲染, 否则它们会原地停留一个动画时长才消失。
        if (skipRowMotion && row.original.isExiting) {
          return null;
        }
        return (
          <tr
            key={row.id}
            className={rowClassName(row.original, disabled, skipRowMotion)}
            aria-hidden={row.original.isExiting || undefined}
            // 退出动画开始即移出可访问树, 避免读屏/Tab 仍命中。React 19 把 inert 当布尔属性: 空串会被当成 false 且不落 DOM。
            inert={row.original.isExiting || disabled}
            onClick={disabled ? undefined : groupRowClickHandler(row.original, onToggleGroup)}
          >
            {row.getVisibleCells().map((cell) => (
              <td
                key={cell.id}
                className={cn(
                  TABLE_CELL_CLASS,
                  cell.column.id === "permission" && "permission-selector__sticky-column",
                  cell.column.id === "scope" && "permission-selector__scope-cell",
                )}
              >
                {/*
                  * <tr> 的高度不能过渡, 因此每格内容再包一层可收拢的容器:
                  * 进出场时由 permission-selector.css 把它的 grid 行高在 1fr / 0fr 之间做动画,
                  * 表格高度与淡入淡出同步变化, 不再在动画结束的瞬间跳一下。
                  */}
                <div className="permission-selector__cell-collapse">
                  <div className="permission-selector__cell-collapse-body">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </div>
                </div>
              </td>
            ))}
          </tr>
        );
      })}
    </tbody>
  );
}

/** 本次渲染里带进出场标记的行数; 阈值判断只看行, 不看单元格。 */
function countMotionRows(rows: Array<{ original: PermissionSelectorRow }>): number {
  let count = 0;
  for (const row of rows) {
    if (row.original.isEntering || row.original.isExiting) {
      count += 1;
    }
  }
  return count;
}

function rowClassName(row: PermissionSelectorRow, disabled: boolean, skipRowMotion: boolean): string {
  return cn(
    TABLE_ROW_CLASS,
    "permission-selector__row",
    row.type === "group" && "permission-selector__row--group bg-paper-deep/60 hover:bg-paper-deep",
    row.type === "group" && row.selectionState !== "unchecked" && "permission-selector__row--group-selected",
    row.type === "permission" && row.isSelected && "permission-selector__row--selected",
    !skipRowMotion && row.isEntering && "permission-selector__row--entering",
    !skipRowMotion && row.isExiting && "permission-selector__row--exiting",
    disabled && "pointer-events-none opacity-60",
  );
}

function groupRowClickHandler(
  row: PermissionSelectorRow,
  onToggleGroup: (key: string) => void,
): ((event: MouseEvent<HTMLTableRowElement>) => void) | undefined {
  return row.type === "group"
    ? (event) => {
        if (eventTargetIsInteractive(event.target)) {
          return;
        }
        onToggleGroup(row.group.key);
      }
    : undefined;
}

function eventTargetIsInteractive(target: EventTarget): boolean {
  return target instanceof Element && Boolean(target.closest("a,button,input,label,select,textarea"));
}
