import {
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
} from "@tanstack/react-table";
import { ArrowRight, Compass } from "lucide-react";

import { Badge } from "../../components/Badge";
import { EmptyState } from "../../components/ui/EmptyState";
import { TableActionCell, TableRowActionButton, TableRowActionLink } from "../../components/ui/TableActions";
import { TableView } from "../../components/ui/TableView";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";
import { useI18n } from "../../i18n/I18nProvider";
import type { AppSummary } from "../../lib/domain";
import { formatDateTime, readinessLabel, readinessTone } from "../../lib/status";
import type { Translator } from "../../lib/status";
import { safeJoin } from "./workspace/utils";

export interface AppRowActions {
  togglePending: boolean;
  deletePending: boolean;
  onToggleActive: (app: AppSummary) => void;
  onDelete: (app: AppSummary) => void;
  onNavigate: (path: string) => void;
}

export function ConsoleAppTable({
  apps,
  isLoading,
  pageCount,
  totalItems,
  pagination,
  onPaginationChange,
  actions,
}: {
  apps: AppSummary[];
  isLoading: boolean;
  pageCount: number;
  totalItems: number;
  pagination: PaginationState;
  onPaginationChange: OnChangeFn<PaginationState>;
  actions: AppRowActions;
}) {
  const { t } = useI18n();
  const table = useReactTable({
    data: apps,
    columns: appColumns(t, actions),
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount,
    state: { pagination },
    onPaginationChange,
  });

  return (
    <TableView
      table={table}
      isLoading={isLoading}
      totalItems={totalItems}
      empty={<EmptyState title={t("appList.empty.title")} description={t("appList.empty.description")} />}
    />
  );
}

function appColumns(t: Translator, actions: AppRowActions): ColumnDef<AppSummary>[] {
  return [
    {
      header: t("appList.column.app"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.name}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.app_key}</code>
        </div>
      ),
    },
    {
      header: t("appList.column.owners"),
      cell: ({ row }) => <span>{safeJoin(row.original.owners)}</span>,
    },
    {
      header: t("appList.column.configuration"),
      cell: ({ row }) => (
        <Badge tone={readinessTone(row.original.configuration_status)}>
          {readinessLabel(t, row.original.configuration_status)}
        </Badge>
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
      cell: ({ row }) => <AppRowActionsCell app={row.original} actions={actions} />,
    },
  ];
}

/** 已就绪或无接入权限的行不需要"继续接入", 但仍要占位保持按钮列对齐。 */
function onboardingResumeHidden(app: AppSummary): boolean {
  return app.configuration_status === "ready" || app.capabilities?.can_manage_catalog !== true;
}

/** 后端只在 capabilities 显式为 true 时才允许该操作, 缺字段一律视为不允许。 */
function canToggleActive(app: AppSummary): boolean {
  return app.capabilities?.can_toggle_active === true;
}

function canDelete(app: AppSummary): boolean {
  return app.capabilities?.can_delete === true;
}

function AppRowActionsCell({ app, actions }: { app: AppSummary; actions: AppRowActions }) {
  const { t } = useI18n();
  const resumeHidden = onboardingResumeHidden(app);
  const resumeHref = `/console/apps/new?app_key=${app.app_key}&step=catalog`;
  const enterHref = `/console/apps/${app.app_key}`;

  return (
    <TableActionCell>
      <TableRowActionButton
        type="button"
        variant={app.is_active ? "ghost-danger" : "ghost"}
        disabled={actions.togglePending || !canToggleActive(app)}
        onClick={() => actions.onToggleActive(app)}
      >
        {app.is_active ? t("common.disable") : t("common.enable")}
      </TableRowActionButton>
      <TableRowActionButton
        type="button"
        variant="ghost-danger"
        disabled={actions.deletePending || !canDelete(app)}
        onClick={() => actions.onDelete(app)}
      >
        {t("common.delete")}
      </TableRowActionButton>
      {/* 已就绪的行以 invisible 占位保持每行操作按钮列对齐 */}
      <TableRowActionLink
        className={resumeHidden ? "invisible" : undefined}
        aria-hidden={resumeHidden || undefined}
        tabIndex={resumeHidden ? -1 : undefined}
        href={resumeHref}
        icon={<Compass size={15} />}
        onClick={(event) => {
          event.preventDefault();
          actions.onNavigate(resumeHref);
        }}
      >
        {t("appList.resumeOnboarding")}
      </TableRowActionLink>
      <TableRowActionLink
        href={enterHref}
        icon={<ArrowRight size={15} />}
        onClick={(event) => {
          event.preventDefault();
          actions.onNavigate(enterHref);
        }}
      >
        {t("common.enter")}
      </TableRowActionLink>
    </TableActionCell>
  );
}
