import type { Table } from "@tanstack/react-table";

import { PaginationBar } from "./PaginationBar";

export { DEFAULT_TABLE_PAGE_SIZE, TABLE_PAGE_SIZE_OPTIONS } from "./PaginationBar";

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
  );
}
