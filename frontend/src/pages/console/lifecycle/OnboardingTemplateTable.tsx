import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";

import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../../components/ui/TableActions";
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
import type { OnboardingTemplateRow } from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import type { Translator } from "../../../lib/status";

export interface TemplateRowActions {
  onEdit: (template: OnboardingTemplateRow) => void;
  onToggle: (template: OnboardingTemplateRow) => void;
  toggling: boolean;
}

export function OnboardingTemplateTable({
  templates,
  isLoading,
  actions,
}: {
  templates: OnboardingTemplateRow[];
  isLoading: boolean;
  actions: TemplateRowActions;
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
                    <TableActionCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableActionCell>
                  ) : (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ),
                )}
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
              <EmptyState
                title={t("onboarding.templates.empty.title")}
                description={t("onboarding.templates.empty.description")}
              />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
    </TableFrame>
  );
}

function templateColumns(t: Translator, actions: TemplateRowActions): ColumnDef<OnboardingTemplateRow>[] {
  return [
    {
      header: t("common.name"),
      cell: ({ row }) => <strong>{row.original.name}</strong>,
    },
    {
      header: t("common.description"),
      cell: ({ row }) => row.original.description || "-",
    },
    {
      header: t("onboarding.templates.column.items"),
      cell: ({ row }) => t("onboarding.templates.itemCount", { count: row.original.items.length }),
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
        <>
          <TableRowActionButton type="button" onClick={() => actions.onEdit(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
          <TableRowActionButton type="button" disabled={actions.toggling} onClick={() => actions.onToggle(row.original)}>
            {row.original.is_active ? t("common.disable") : t("common.enable")}
          </TableRowActionButton>
        </>
      ),
    },
  ];
}
