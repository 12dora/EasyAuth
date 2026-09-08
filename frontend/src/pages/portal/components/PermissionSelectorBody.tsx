import { flexRender, type Table } from "@tanstack/react-table";
import { useState, type MouseEvent } from "react";

import { EmptyState } from "../../../components/ui/EmptyState";
import { cn } from "../../../lib/cn";
import { useI18n } from "../../../i18n/I18nProvider";

import { permissionSelectorTableMeta } from "./permissionSelectorMeta";
import { TABLE_CELL_CLASS, TABLE_ROW_CLASS } from "./permissionSelectorPrimitives";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

/*
 * 同时逐行做动画的行数上限。
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
  /*
   * 过渡批次的决定跟着渲染走, 不能写在 ref 里: ref 是绕过 React 状态的副作用,
   * 并发渲染下一次被丢弃的渲染也会把决定留下来, 泄漏到下一次真正提交的渲染里。
   * 放进 state + 渲染期推进(与 useGroupTransitionKeys 同一套做法): 渲染被丢弃,
   * 这次的决定也跟着一起作废。本次渲染直接用刚算出来的 next, 不必等下一轮。
   */
  const [committedRowMotionSkips, setCommittedRowMotionSkips] = useState(EMPTY_ROW_MOTION_SKIPS);
  const rowMotionSkips = nextRowMotionSkips(committedRowMotionSkips, rows);
  if (rowMotionSkips !== committedRowMotionSkips) {
    setCommittedRowMotionSkips(rowMotionSkips);
  }
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
        const skipRowMotion = rowMotionSkips.get(row.id) === true;
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

const EMPTY_ROW_MOTION_SKIPS: ReadonlyMap<string, boolean> = new Map();

/**
 * 行 id -> 这一行所属的那批过渡要不要跳过逐行动画。
 *
 * 决定必须跟着"批次"活到过渡结束, 不能每次渲染按当时的行数重算。
 * 反例: 两个 30 行的组间隔 80ms 先后收起 —— 第二批到来时在场的过渡行有 60 行(超阈值)
 * 因而被跳过; 等第一批的计时器到点、行数掉回 30, 重算就会把第二批从"跳过"翻回"要动画",
 * 已经摘掉的行重新挂上、重放一遍退场动画, 再被第一批那个计时器提前摘走。
 * 所以已经定下的决定只跟着行一起淘汰, 不重新判定。
 *
 * 新一批的代价要把"还在播的行"一起算进去: 它们仍在每帧参与重排。
 * 已经定下的决定不会因此改变, 所以不存在上面那种来回翻转。
 *
 * 纯函数: 集合没有变化时原样返回上一份, 渲染期的 setState 因此不会自激。
 */
function nextRowMotionSkips(
  current: ReadonlyMap<string, boolean>,
  rows: Array<{ id: string; original: PermissionSelectorRow }>,
): ReadonlyMap<string, boolean> {
  const motionRowIds = new Set<string>();
  for (const row of rows) {
    if (row.original.isEntering || row.original.isExiting) {
      motionRowIds.add(row.id);
    }
  }

  const keptRowIds = [...current.keys()].filter((rowId) => motionRowIds.has(rowId));
  const freshRowIds = [...motionRowIds].filter((rowId) => !current.has(rowId));
  if (keptRowIds.length === current.size && freshRowIds.length === 0) {
    return current;
  }

  const next = new Map<string, boolean>();
  let animatingCount = 0;
  for (const rowId of keptRowIds) {
    const skip = current.get(rowId) === true;
    next.set(rowId, skip);
    if (!skip) {
      animatingCount += 1;
    }
  }
  if (freshRowIds.length > 0) {
    const skip = animatingCount + freshRowIds.length > ROW_MOTION_LIMIT;
    for (const rowId of freshRowIds) {
      next.set(rowId, skip);
    }
  }
  return next;
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
