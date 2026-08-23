/** 权限选择器表格与分页视图, 不持有筛选和选择状态。 */

import { flexRender, type Table } from "@tanstack/react-table";

import { PaginationBar } from "../../../components/ui/PaginationBar";
import {
  TABLE_HEAD_CLASS,
  TABLE_HEADER_CELL_CLASS,
  TABLE_ROOT_CLASS,
  TABLE_ROW_CLASS,
} from "../../../components/ui/tableStyles";
import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";

import { PermissionSelectorBody } from "./PermissionSelectorBody";
import type { PermissionSelectorRow } from "./permissionSelectorRows";

export function PermissionSelectorTable({
  table,
  disabled,
  showSelectedOnly,
  onToggleGroup,
}: {
  table: Table<PermissionSelectorRow>;
  disabled: boolean;
  showSelectedOnly: boolean;
  onToggleGroup: (key: string) => void;
}) {
  const { t } = useI18n();
  const pagination = table.getState().pagination;
  const totalRows = table.getPrePaginationRowModel().rows.length;
  const visibleRows = table.getRowModel().rows;
  const pageStart = totalRows === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1;
  const pageEnd = totalRows === 0 ? 0 : pageStart + visibleRows.length - 1;

  return (
    <>
      <div className="overflow-x-auto">
        <table aria-label={t("selector.ariaLabel")} className={TABLE_ROOT_CLASS}>
          <thead className={TABLE_HEAD_CLASS}>
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
          <PermissionSelectorBody
            rows={visibleRows}
            columnCount={table.getAllLeafColumns().length}
            disabled={disabled}
            showSelectedOnly={showSelectedOnly}
            onToggleGroup={onToggleGroup}
          />
        </table>
      </div>
      <PaginationBar
        pageStart={pageStart}
        pageEnd={pageEnd}
        totalRows={totalRows}
        pageSize={pagination.pageSize}
        pageIndex={pagination.pageIndex}
        pageCount={table.getPageCount()}
        canPreviousPage={table.getCanPreviousPage()}
        canNextPage={table.getCanNextPage()}
        onPageSizeChange={(pageSize) => {
          table.setPageIndex(0);
          table.setPageSize(pageSize);
        }}
        onPreviousPage={() => table.previousPage()}
        onNextPage={() => table.nextPage()}
      />
    </>
  );
}
