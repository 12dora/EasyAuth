/** 渲染权限组、作用域和权限目录的表格区块。 */

import { Plus } from "lucide-react";

import { Button } from "../../../../components/Button";
import { AppTable, type ColumnsType } from "../../../../components/antd/AppTable";
import { actionsColumn, statusColumn, textColumn } from "../../../../components/antd/columns";
import { EmptyState } from "../../../../components/ui/EmptyState";
import type { AppScopeItem, PermissionGroupItem, PermissionItem } from "../../../../lib/domain";
import { useI18n } from "../../../../i18n/I18nProvider";
import { activeStatusColumn, RowActionButton } from "../workspaceColumns";

/** 三张目录表都放在半宽栅格里, 列多于四列时给一个统一的最小宽度。 */
const CATALOG_TABLE_MIN_WIDTH = 640;

export function CatalogGroupsPanel({ rows, isLoading, onCreate, onEdit }: {
  rows: PermissionGroupItem[];
  isLoading: boolean;
  onCreate: () => void;
  onEdit: (group: PermissionGroupItem) => void;
}) {
  const { t } = useI18n();
  const columns: ColumnsType<PermissionGroupItem> = [
    textColumn<PermissionGroupItem>({
      key: "key",
      title: t("console.catalog.group.column.key"),
      mono: true,
      filter: true,
      width: 180,
    }),
    textColumn<PermissionGroupItem>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    {
      key: "depth",
      dataIndex: "depth",
      title: t("console.catalog.group.column.depth"),
      width: 90,
      sorter: (a, b) => (a.depth ?? 0) - (b.depth ?? 0),
      render: (_value: unknown, group: PermissionGroupItem) => group.depth ?? "-",
    },
    {
      key: "permissionCount",
      title: t("console.catalog.group.column.permissionCount"),
      width: 110,
      sorter: (a, b) => (a.permissions?.length ?? 0) - (b.permissions?.length ?? 0),
      render: (_value: unknown, group: PermissionGroupItem) => group.permissions?.length ?? 0,
    },
    actionsColumn<PermissionGroupItem>({
      title: t("common.actions"),
      render: (group) => (
        <RowActionButton type="button" onClick={() => onEdit(group)}>
          {t("common.edit")}
        </RowActionButton>
      ),
    }),
  ];

  return (
    <section className="space-y-3">
      <CatalogPanelHeading title={t("console.catalog.groups")} onCreate={onCreate} />
      <AppTable<PermissionGroupItem>
        columns={columns}
        dataSource={rows}
        rowKey="key"
        loading={isLoading}
        minWidth={CATALOG_TABLE_MIN_WIDTH}
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
  const columns: ColumnsType<AppScopeItem> = [
    textColumn<AppScopeItem>({
      key: "key",
      title: t("console.catalog.scope.column.key"),
      mono: true,
      filter: true,
      width: 180,
    }),
    textColumn<AppScopeItem>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    {
      key: "display_order",
      dataIndex: "display_order",
      title: t("console.catalog.scope.column.order"),
      width: 90,
      sorter: (a, b) => a.display_order - b.display_order,
    },
    activeStatusColumn<AppScopeItem>({ t, getActive: (scope) => scope.is_active }),
    actionsColumn<AppScopeItem>({
      title: t("common.actions"),
      render: (scope) => (
        <>
          <RowActionButton type="button" onClick={() => onEdit(scope)}>{t("common.edit")}</RowActionButton>
          <RowActionButton
            type="button"
            variant={scope.is_active ? "ghost-danger" : "ghost"}
            disabled={togglePending}
            onClick={() => onToggle(scope)}
          >
            {scope.is_active ? t("common.disable") : t("common.enable")}
          </RowActionButton>
        </>
      ),
    }),
  ];

  return (
    <section className="space-y-3">
      <CatalogPanelHeading title={t("console.catalog.scopes")} onCreate={onCreate} />
      <AppTable<AppScopeItem>
        columns={columns}
        dataSource={scopes}
        rowKey="key"
        loading={isLoading}
        minWidth={CATALOG_TABLE_MIN_WIDTH}
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
  const columns: ColumnsType<PermissionItem> = [
    textColumn<PermissionItem>({
      key: "key",
      title: t("console.catalog.permission.column.key"),
      mono: true,
      filter: true,
      width: 220,
    }),
    textColumn<PermissionItem>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    textColumn<PermissionItem>({
      key: "group_key",
      title: t("console.catalog.permission.column.group"),
      filter: true,
      width: 160,
    }),
    textColumn<PermissionItem>({
      key: "supported_scopes",
      title: t("console.catalog.permission.column.scopes"),
      getValue: (permission) => (permission.supported_scopes ?? []).join("、"),
      filter: true,
      width: 200,
    }),
    statusColumn<PermissionItem>({
      key: "risk_level",
      title: t("console.catalog.permission.column.risk"),
      width: 120,
      options: [
        { value: "high", label: t("console.catalog.risk.high"), tone: "signal" },
        { value: "standard", label: t("console.catalog.risk.standard"), tone: "neutral" },
      ],
      // 旧表把缺省风险级别视为「标准」, 迁移后保持同一口径。
      getValue: (permission) => permission.risk_level || "standard",
    }),
    actionsColumn<PermissionItem>({
      title: t("common.actions"),
      render: (permission) => (
        <RowActionButton type="button" onClick={() => onEdit(permission)}>
          {t("common.edit")}
        </RowActionButton>
      ),
    }),
  ];

  return (
    <section className="space-y-3">
      <CatalogPanelHeading title={t("console.catalog.permissions")} onCreate={onCreate} />
      <AppTable<PermissionItem>
        columns={columns}
        dataSource={permissions}
        rowKey="key"
        loading={isLoading}
        minWidth={960}
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
