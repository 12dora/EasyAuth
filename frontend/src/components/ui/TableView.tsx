import { flexRender, type Table } from "@tanstack/react-table";
import { Fragment, type ReactNode } from "react";

import { TablePagination } from "./TablePagination";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
  TableSkeletonRows,
} from "./TablePrimitives";

interface TableViewProps<T> {
  table: Table<T>;
  empty: ReactNode;
  /** 为真时表体渲染骨架行, 与行数据/空态互斥。 */
  isLoading?: boolean;
  /** 传入总条目数时渲染分页栏。 */
  totalItems?: number;
  ariaLabel?: string;
  getCellClassName?: (columnId: string) => string | undefined;
}

/**
 * TanStack 表格共用渲染骨架: 表头 + (骨架行 | 数据行 | 空行) + 可选分页。
 * id 为 actions 的列由 cell 自行渲染 td, 因此不再包一层 TableCell。
 */
export function TableView<T>({
  table,
  empty,
  isLoading = false,
  totalItems,
  ariaLabel,
  getCellClassName,
}: TableViewProps<T>) {
  const columnCount = table.getAllLeafColumns().length;
  const rows = table.getRowModel().rows;

  return (
    <TableFrame>
      <TableRoot aria-label={ariaLabel}>
        <TableHead>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHeaderCell key={header.id}>
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHeaderCell>
              ))}
            </TableRow>
          ))}
        </TableHead>
        <TableBody>
          {isLoading ? (
            <TableSkeletonRows columns={columnCount} />
          ) : rows.length > 0 ? (
            rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) =>
                  cell.column.id === "actions" ? (
                    <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                  ) : (
                    <TableCell key={cell.id} className={getCellClassName?.(cell.column.id)}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ),
                )}
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={columnCount}>{empty}</TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
      {totalItems === undefined ? null : <TablePagination table={table} totalItems={totalItems} />}
    </TableFrame>
  );
}
