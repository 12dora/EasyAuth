/** 权限选择器表格视图, 不持有筛选和选择状态。 */

import { flexRender, type Table } from "@tanstack/react-table";

import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";

import { PermissionSelectorBody } from "./PermissionSelectorBody";
import {
  TABLE_HEAD_CLASS,
  TABLE_HEADER_CELL_CLASS,
  TABLE_ROOT_CLASS,
  TABLE_ROW_CLASS,
} from "./permissionSelectorPrimitives";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

export function PermissionSelectorTable({ table }: { table: Table<PermissionSelectorRow> }) {
  const { t } = useI18n();

  /*
   * 权限目录不分页: 权限之间是树关系, 翻页会把同一个权限组的权限切到两页去,
   * 「展开全部 / 全选」这类操作也只能作用于当前页。整棵树一次渲染完, 高度封在
   * 一个固定高度的滚动容器里, 表头粘在容器顶部, 滚到第 200 行也还看得见列名。
   *
   * thead 的层级要压过粘在左侧的权限列(z-index 10, 见 permission-selector.css),
   * 否则纵向滚动时权限名会盖在表头上。
   */
  return (
    <div className="max-h-[28rem] overflow-x-auto overflow-y-auto">
      <table aria-label={t("selector.ariaLabel")} className={TABLE_ROOT_CLASS}>
        <thead className={cn(TABLE_HEAD_CLASS, "sticky top-0 z-20")}>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id} className={TABLE_ROW_CLASS}>
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  colSpan={header.colSpan}
                  className={cn(
                    TABLE_HEADER_CELL_CLASS,
                    header.column.id === "permission" &&
                      "permission-selector__sticky-column permission-selector__sticky-column--header",
                    header.column.id === "scope" && "permission-selector__scope-cell",
                  )}
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <PermissionSelectorBody table={table} />
      </table>
    </div>
  );
}
