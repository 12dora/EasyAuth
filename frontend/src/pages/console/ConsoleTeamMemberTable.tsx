import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { Fragment } from "react";

import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../components/ui/TableActions";
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
} from "../../components/ui/TablePrimitives";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";
import { useI18n } from "../../i18n/I18nProvider";
import type { TeamMemberItem } from "../../lib/domain";
import { formatDateTime } from "../../lib/status";
import type { Translator } from "../../lib/status";
import { teamMemberRoleLabel } from "./consoleTeamDetailModel";

export interface TeamMemberTableActions {
  disabled: boolean;
  onToggleRole: (member: TeamMemberItem) => void;
  onRemove: (member: TeamMemberItem) => void;
}

export function ConsoleTeamMemberTable({
  members,
  isLoading,
  actions,
}: {
  members: TeamMemberItem[];
  isLoading: boolean;
  actions: TeamMemberTableActions;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: members,
    columns: teamMemberTableColumns(t, actions),
    getCoreRowModel: getCoreRowModel(),
  });

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
              <EmptyState title={t("console.teams.membersEmpty")} description={t("console.teams.membersEmptyDescription")} />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
    </TableFrame>
  );
}

function teamMemberTableColumns(t: Translator, actions: TeamMemberTableActions): ColumnDef<TeamMemberItem>[] {
  return [
    {
      header: t("console.teams.column.member"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.name || row.original.user_id}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.user_id}</code>
        </div>
      ),
    },
    {
      header: t("console.teams.column.department"),
      cell: ({ row }) => row.original.department || "-",
    },
    {
      header: t("common.role"),
      cell: ({ row }) => (
        <Badge tone={row.original.role === "leader" ? "bond" : "neutral"}>
          {teamMemberRoleLabel(t, row.original.role)}
        </Badge>
      ),
    },
    {
      header: t("console.teams.column.addedAt"),
      cell: ({ row }) => formatDateTime(row.original.added_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" disabled={actions.disabled} onClick={() => actions.onToggleRole(row.original)}>
            {row.original.role === "leader" ? t("console.teams.setMember") : t("console.teams.setLeader")}
          </TableRowActionButton>
          <TableRowActionButton type="button" variant="ghost-danger" disabled={actions.disabled} onClick={() => actions.onRemove(row.original)}>
            {t("common.remove")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
}
