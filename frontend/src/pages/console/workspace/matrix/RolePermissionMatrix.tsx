import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMemo } from "react";
import { TableBody, TableCell, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";
import { TablePagination } from "../../../../components/ui/TablePagination";

import type { MatrixPayload } from "../../../../lib/domain";
import { matrixCellKey } from "./useMatrixDraft";

interface RolePermissionMatrixProps {
  matrix: MatrixPayload | undefined;
  isCellEnabled: (roleId: number, permissionId: number) => boolean;
  onCellChange: (roleId: number, permissionId: number, enabled: boolean) => void;
}

export function RolePermissionMatrix({ matrix, isCellEnabled, onCellChange }: RolePermissionMatrixProps) {
  const roles = matrix?.roles ?? [];
  const permissions = matrix?.permissions ?? [];
  const columns = useMemo<ColumnDef<(typeof permissions)[number]>[]>(
    () => [
      {
        id: "permission",
        header: "权限",
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-1">
            <strong className="text-sm font-semibold text-ink">{row.original.name}</strong>
            <code className="text-xs text-ink-soft">{row.original.key}</code>
          </div>
        ),
      },
      ...roles.map(
        (role): ColumnDef<(typeof permissions)[number]> => ({
          id: String(role.id),
          header: role.name,
          cell: ({ row }) => (
            <input
              type="checkbox"
              checked={isCellEnabled(role.id, row.original.id)}
              onChange={(event) => onCellChange(role.id, row.original.id, event.currentTarget.checked)}
              aria-label={`${role.key} ${row.original.key}`}
            />
          ),
        }),
      ),
    ],
    [isCellEnabled, onCellChange, permissions, roles],
  );
  const table = useReactTable({
    data: permissions,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (permission) => String(permission.id),
  });

  return (
    <TableFrame className="max-w-full">
      <TableRoot>
        <TableHead>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHeaderCell
                  key={header.id}
                  className={header.column.id === "permission" ? "sticky left-0 z-20 min-w-60 bg-paper-deep" : "text-center"}
                >
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHeaderCell>
              ))}
            </TableRow>
          ))}
        </TableHead>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell
                  key={cell.column.id === "permission" ? cell.id : matrixCellKey(Number(cell.column.id), row.original.id)}
                  className={cell.column.id === "permission" ? "sticky left-0 z-10 min-w-60 bg-inherit" : "text-center"}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} />
    </TableFrame>
  );
}
