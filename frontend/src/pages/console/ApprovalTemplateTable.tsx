import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMemo } from "react";

import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../components/ui/TableActions";
import { TableView } from "../../components/ui/TableView";
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
  const columns = useMemo(
    () => templateColumns(t, actions),
    [actions.onDelete, actions.onEdit, actions.onTest, t],
  );
  const table = useReactTable({
    data: templates,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <TableView
      table={table}
      isLoading={isLoading}
      empty={<EmptyState title={t("approvalTemplates.empty.title")} description={t("approvalTemplates.empty.description")} />}
    />
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
