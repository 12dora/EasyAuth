import { flexRender, type Table } from "@tanstack/react-table";
import { Fragment, type ReactNode } from "react";

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
} from "../../../../components/ui/TablePrimitives";
import { TablePagination } from "../../../../components/ui/TablePagination";

interface WorkspaceTableProps<T> {
  table: Table<T>;
  totalItems: number;
  empty: ReactNode;
  /** 为真时表体渲染骨架行, 与行数据/空态互斥。 */
  isLoading?: boolean;
}

/**
 * 工作台各页签共用的 TanStack 表格渲染骨架:
 * 表头 + (骨架行 | 数据行 | 空行) + 分页。
 * id 为 actions 的列由 cell 自行渲染 td(TableActionCell), 因此不再包一层 TableCell。
 */
export function WorkspaceTable<T>({ table, totalItems, empty, isLoading = false }: WorkspaceTableProps<T>) {
  const columnCount = table.getAllLeafColumns().length;
  const rows = table.getRowModel().rows;

  return (
    <TableFrame>
      <TableRoot>
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
                {row.getVisibleCells().map((cell) => (
                  cell.column.id === "actions" ? (
                    <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
                  ) : (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  )
                ))}
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={columnCount}>{empty}</TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} totalItems={totalItems} />
    </TableFrame>
  );
}
