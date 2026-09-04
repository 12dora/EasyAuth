import { flexRender, type Table } from "@tanstack/react-table";
import type { MouseEvent } from "react";

import { EmptyState } from "../../../components/ui/EmptyState";
import { cn } from "../../../lib/cn";
import { useI18n } from "../../../i18n/I18nProvider";

import { permissionSelectorTableMeta } from "./permissionSelectorMeta";
import { TABLE_CELL_CLASS, TABLE_ROW_CLASS } from "./permissionSelectorPrimitives";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

export function PermissionSelectorBody({ table }: { table: Table<PermissionSelectorRow> }) {
  const { t } = useI18n();
  const { disabled, showSelectedOnly, onToggleGroup } = permissionSelectorTableMeta(table);
  const rows = table.getRowModel().rows;
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
      {rows.map((row) => (
        <tr
          key={row.id}
          className={rowClassName(row.original, disabled)}
          aria-hidden={row.original.isExiting || undefined}
          // 退出动画开始即移出可访问树, 避免读屏/Tab 仍命中。
          {...(row.original.isExiting || disabled ? ({ inert: "" } as object) : {})}
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
      ))}
    </tbody>
  );
}

function rowClassName(row: PermissionSelectorRow, disabled: boolean): string {
  return cn(
    TABLE_ROW_CLASS,
    "permission-selector__row",
    row.type === "group" && "permission-selector__row--group bg-paper-deep/60 hover:bg-paper-deep",
    row.type === "group" && row.selectionState !== "unchecked" && "permission-selector__row--group-selected",
    row.type === "permission" && row.isSelected && "permission-selector__row--selected",
    row.isEntering && "permission-selector__row--entering",
    row.isExiting && "permission-selector__row--exiting",
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
