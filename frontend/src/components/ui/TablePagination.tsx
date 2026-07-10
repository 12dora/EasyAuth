import type { Table } from "@tanstack/react-table";

import { PaginationBar } from "./PaginationBar";

export { DEFAULT_TABLE_PAGE_SIZE, TABLE_PAGE_SIZE_OPTIONS } from "./PaginationBar";

interface TablePaginationProps<T> {
  table: Table<T>;
  totalItems: number;
}

export function TablePagination<T>({ table, totalItems }: TablePaginationProps<T>) {
  const pagination = table.getState().pagination;
  const currentRows = table.getRowModel().rows.length;
  const pageStart = totalItems === 0 || currentRows === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1;
  const pageEnd = pageStart === 0 ? 0 : Math.min(totalItems, pageStart + currentRows - 1);

  return (
    <PaginationBar
      pageStart={pageStart}
      pageEnd={pageEnd}
      totalRows={totalItems}
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
  );
}
