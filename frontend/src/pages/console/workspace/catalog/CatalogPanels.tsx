/** 渲染权限组、作用域和权限目录的表格区块。 */

import { getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import { TableView } from "../../../../components/ui/TableView";
import type { AppScopeItem, PermissionGroupItem, PermissionItem } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { useI18n } from "../../../../i18n/I18nProvider";

export function CatalogGroupsPanel({ rows, isLoading, onCreate, onEdit }: {
  rows: PermissionGroupItem[];
  isLoading: boolean;
  onCreate: () => void;
  onEdit: (group: PermissionGroupItem) => void;
}) {
  const { t } = useI18n();
  const columns: ColumnDef<PermissionGroupItem>[] = [
    { header: t("console.catalog.group.column.key"), cell: ({ row }) => <code>{row.original.key}</code> },
    { header: t("common.name"), accessorKey: "name" },
    { header: t("console.catalog.group.column.depth"), cell: ({ row }) => row.original.depth ?? "-" },
    { header: t("console.catalog.group.column.permissionCount"), cell: ({ row }) => row.original.permissions?.length ?? 0 },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => onEdit(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel(), getPaginationRowModel: getPaginationRowModel() });
  return (
    <section className="space-y-3">
      <CatalogPanelHeading title={t("console.catalog.groups")} onCreate={onCreate} />
      <TableView
        table={table}
        totalItems={rows.length}
        isLoading={isLoading}
        empty={<EmptyState title={t("console.catalog.groupsEmpty")} description={t("console.catalog.groupsEmptyDescription")} />}
      />
    </section>
  );
}

export function CatalogScopesPanel({ scopes, isLoading, togglePending, onCreate, onEdit, onToggle }: {
  scopes: AppScopeItem[];
  isLoading: boolean;
  togglePending: boolean;
  onCreate: () => void;
  onEdit: (scope: AppScopeItem) => void;
  onToggle: (scope: AppScopeItem) => void;
}) {
  const { t } = useI18n();
  const columns: ColumnDef<AppScopeItem>[] = [
    { header: t("console.catalog.scope.column.key"), cell: ({ row }) => <code>{row.original.key}</code> },
    { header: t("common.name"), accessorKey: "name" },
    { header: t("console.catalog.scope.column.order"), accessorKey: "display_order" },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>{row.original.is_active ? t("common.enabled") : t("common.disabled")}</Badge> },
    {
      id: "actions", header: t("common.actions"), cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => onEdit(row.original)}>{t("common.edit")}</TableRowActionButton>
          <TableRowActionButton
            type="button"
            variant={row.original.is_active ? "ghost-danger" : "ghost"}
            disabled={togglePending}
            onClick={() => onToggle(row.original)}
          >
            {row.original.is_active ? t("common.disable") : t("common.enable")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const table = useReactTable({ data: scopes, columns, getCoreRowModel: getCoreRowModel(), getPaginationRowModel: getPaginationRowModel() });
  return (
    <section className="space-y-3">
      <CatalogPanelHeading title={t("console.catalog.scopes")} onCreate={onCreate} />
      <TableView
        table={table}
        totalItems={scopes.length}
        isLoading={isLoading}
        empty={<EmptyState title={t("console.catalog.scopesEmpty")} description={t("console.catalog.scopesEmptyDescription")} />}
      />
    </section>
  );
}

export function CatalogPermissionsPanel({ permissions, isLoading, onCreate, onEdit }: {
  permissions: PermissionItem[];
  isLoading: boolean;
  onCreate: () => void;
  onEdit: (permission: PermissionItem) => void;
}) {
  const { t } = useI18n();
  const columns: ColumnDef<PermissionItem>[] = [
    { header: t("console.catalog.permission.column.key"), cell: ({ row }) => <code>{row.original.key}</code> },
    { header: t("common.name"), accessorKey: "name" },
    { header: t("console.catalog.permission.column.group"), cell: ({ row }) => row.original.group_key || "-" },
    { header: t("console.catalog.permission.column.scopes"), cell: ({ row }) => (row.original.supported_scopes ?? []).join("、") || "-" },
    { header: t("console.catalog.permission.column.risk"), cell: ({ row }) => <Badge tone={row.original.risk_level === "high" ? "signal" : "neutral"}>{riskLevelLabel(t, row.original.risk_level)}</Badge> },
    {
      id: "actions", header: t("common.actions"), cell: ({ row }) => (
        <TableActionCell>
          <TableRowActionButton type="button" onClick={() => onEdit(row.original)}>
            {t("common.edit")}
          </TableRowActionButton>
        </TableActionCell>
      ),
    },
  ];
  const table = useReactTable({ data: permissions, columns, getCoreRowModel: getCoreRowModel(), getPaginationRowModel: getPaginationRowModel() });
  return (
    <section className="space-y-3">
      <CatalogPanelHeading title={t("console.catalog.permissions")} onCreate={onCreate} />
      <TableView
        table={table}
        totalItems={permissions.length}
        isLoading={isLoading}
        empty={<EmptyState title={t("console.catalog.permissionsEmpty")} description={t("console.catalog.permissionsEmptyDescription")} />}
      />
    </section>
  );
}

function CatalogPanelHeading({ title, onCreate }: { title: string; onCreate: () => void }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={onCreate}>
        {t("common.new")}
      </Button>
    </div>
  );
}

function riskLevelLabel(t: Translator, value: string | undefined): string {
  if (value === "high") {
    return t("console.catalog.risk.high");
  }
  if (value === "standard" || !value) {
    return t("console.catalog.risk.standard");
  }
  return value;
}
