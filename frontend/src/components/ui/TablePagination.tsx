import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Table } from "@tanstack/react-table";

import { Button } from "../Button";
import { SelectInput } from "../Field";

export const DEFAULT_TABLE_PAGE_SIZE = 10;
export const TABLE_PAGE_SIZE_OPTIONS = [5, 10, 20, 50] as const;

interface TablePaginationProps<T> {
  table: Table<T>;
}

export function TablePagination<T>({ table }: TablePaginationProps<T>) {
  const pagination = table.getState().pagination;
  const totalRows = table.getPrePaginationRowModel().rows.length;
  const currentRows = table.getRowModel().rows.length;
  const pageStart = totalRows === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1;
  const pageEnd = totalRows === 0 ? 0 : pageStart + currentRows - 1;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 bg-paper-deep/30 px-3 py-2.5">
      <span className="text-[12px] font-medium text-ink-soft">
        第 {pageStart}-{pageEnd} 条 / 共 {totalRows} 条
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-[12px] font-medium text-ink-soft">
          每页
          <SelectInput
            aria-label="每页条目数"
            className="h-8 w-20"
            value={String(pagination.pageSize)}
            onChange={(event) => {
              table.setPageIndex(0);
              table.setPageSize(Number(event.currentTarget.value));
            }}
          >
            {TABLE_PAGE_SIZE_OPTIONS.map((pageSize) => (
              <option key={pageSize} value={pageSize}>
                {pageSize}
              </option>
            ))}
          </SelectInput>
        </label>
        <div className="flex items-center gap-1">
          <Button
            aria-label="上一页"
            icon={<ChevronLeft size={15} />}
            disabled={!table.getCanPreviousPage()}
            onClick={() => table.previousPage()}
            size="sm"
            type="button"
          />
          <span className="min-w-16 text-center font-mono text-[12px] text-ink-soft">
            {table.getPageCount() === 0 ? 0 : pagination.pageIndex + 1} / {table.getPageCount()}
          </span>
          <Button
            aria-label="下一页"
            icon={<ChevronRight size={15} />}
            disabled={!table.getCanNextPage()}
            onClick={() => table.nextPage()}
            size="sm"
            type="button"
          />
        </div>
      </div>
    </div>
  );
}
