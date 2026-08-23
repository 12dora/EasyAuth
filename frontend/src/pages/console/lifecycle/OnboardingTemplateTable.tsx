import { getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";

import { Badge } from "../../../components/Badge";
import { EmptyState } from "../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../../components/ui/TableActions";
import { TableView } from "../../../components/ui/TableView";
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
    <TableView
      table={table}
      isLoading={isLoading}
      empty={
        <EmptyState
          title={t("onboarding.templates.empty.title")}
          description={t("onboarding.templates.empty.description")}
        />
      }
    />
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
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => actions.onEdit(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
          <TableRowActionButton type="button" disabled={actions.toggling} onClick={() => actions.onToggle(row.original)}>
            {row.original.is_active ? t("common.disable") : t("common.enable")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
}
