import { flexRender } from "@tanstack/react-table";
import type { Table } from "@tanstack/react-table";
import { Fragment } from "react";

import { EmptyState } from "../../../components/ui/EmptyState";
import { TablePagination } from "../../../components/ui/TablePagination";
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
} from "../../../components/ui/TablePrimitives";
import { useI18n } from "../../../i18n/I18nProvider";
import type { OperationRow } from "./operationRow";

export function OperationsTable({
  table,
  isLoading,
  totalItems,
}: {
  table: Table<OperationRow>;
  isLoading: boolean;
  totalItems: number;
}) {
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
        <OperationsTableBody table={table} isLoading={isLoading} />
      </TableRoot>
      <TablePagination table={table} totalItems={totalItems} />
    </TableFrame>
  );
}

function OperationsTableBody({
  table,
  isLoading,
}: {
  table: Table<OperationRow>;
  isLoading: boolean;
}) {
  const { t } = useI18n();

  return (
    <TableBody>
      {isLoading ? (
        <TableSkeletonRows columns={table.getAllLeafColumns().length} />
      ) : table.getRowModel().rows.length > 0 ? (
        table.getRowModel().rows.map((row) => (
          <TableRow key={row.id}>
            {row.getVisibleCells().map((cell) =>
              cell.column.id === "actions" ? (
                <Fragment key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</Fragment>
              ) : (
                <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
              ),
            )}
          </TableRow>
        ))
      ) : (
        <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
          <EmptyState title={t("console.operations.empty")} description={t("console.operations.emptyDescription")} />
        </TableEmptyRow>
      )}
    </TableBody>
  );
}
