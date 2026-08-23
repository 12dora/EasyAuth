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
import type { ApprovalTemplateItem } from "../../lib/domain";
import { formatDateTime } from "../../lib/status";
import type { Translator } from "../../lib/status";

export interface ApprovalTemplateRowActions {
  onEdit: (template: ApprovalTemplateItem) => void;
  onTest: (template: ApprovalTemplateItem) => void;
  onDelete: (template: ApprovalTemplateItem) => void;
}

export function ApprovalTemplateTable({
  templates,
  isLoading,
  actions,
}: {
  templates: ApprovalTemplateItem[];
  isLoading: boolean;
  actions: ApprovalTemplateRowActions;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: templates,
    columns: templateColumns(t, actions),
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
              <EmptyState title={t("approvalTemplates.empty.title")} description={t("approvalTemplates.empty.description")} />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
    </TableFrame>
  );
}

function templateColumns(t: Translator, actions: ApprovalTemplateRowActions): ColumnDef<ApprovalTemplateItem>[] {
  return [
    {
      header: t("approvalTemplates.column.key"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{row.original.key}</code>,
    },
    {
      header: t("common.name"),
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      header: t("approvalTemplates.column.app"),
      cell: ({ row }) =>
        row.original.app_key ? (
          <code className={MONO_TEXT_CLASS}>{row.original.app_key}</code>
        ) : (
          <Badge tone="bond">{t("approvalTemplates.platformShared")}</Badge>
        ),
    },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>
          {row.original.is_active ? t("common.enabled") : t("common.disabled")}
        </Badge>
      ),
    },
    {
      header: t("common.updatedAt"),
      cell: ({ row }) => formatDateTime(row.original.updated_at),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => actions.onEdit(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
          <TableRowActionButton type="button" onClick={() => actions.onTest(row.original)}>
            {t("approvalTemplates.test.action")}
          </TableRowActionButton>
          <TableRowActionButton type="button" variant="ghost-danger" onClick={() => actions.onDelete(row.original)}>
            {t("common.delete")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
}
