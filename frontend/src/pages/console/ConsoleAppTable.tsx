import { ArrowRight, Compass } from "lucide-react";
import { useMemo } from "react";

import { AppTable, type ColumnsType, type UseServerTableResult } from "../../components/antd/AppTable";
import {
  RowActionButton,
  RowActionLink,
  actionsColumn,
  dateTimeColumn,
  serverColumn,
  statusColumn,
  textColumn,
  userColumn,
} from "../../components/antd/columns";
import { useI18n } from "../../i18n/I18nProvider";
import type { AppSummary } from "../../lib/domain";
import { readinessLabel, readinessTone } from "../../lib/status";
import type { Translator } from "../../lib/status";
import { safeJoin } from "./workspace/utils";

export interface AppRowActions {
  togglePending: boolean;
  deletePending: boolean;
  onToggleActive: (app: AppSummary) => void;
  onDelete: (app: AppSummary) => void;
  onNavigate: (path: string) => void;
}

/** 后端 `_filter_app_status` 只认 active / inactive 两个值。 */
const APP_STATUS_VALUES = ["active", "inactive"] as const;
/** configuration_readiness 的三个状态; 后端不支持按它过滤, 因此只做展示。 */
const READINESS_VALUES = ["ready", "warning", "blocking"] as const;

export function ConsoleAppTable({
  apps,
  isLoading,
  tableProps,
  filters,
  actions,
}: {
  apps: AppSummary[];
  isLoading: boolean;
  tableProps: UseServerTableResult<AppSummary>["tableProps"];
  /** 列 key -> 已选筛选值, 来自 useServerTable 的查询状态(owners / status 都在后端筛)。 */
  filters: Record<string, string[]>;
  actions: AppRowActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => appColumns(t, filters, actions), [actions, filters, t]);

  return (
    <AppTable<AppSummary>
      {...tableProps}
      columns={columns}
      dataSource={apps}
      emptyDescription={t("appList.empty.description")}
      emptyTitle={t("appList.empty.title")}
      loading={isLoading}
      minWidth={1180}
      rowKey="app_key"
    />
  );
}

function appColumns(
  t: Translator,
  filters: Record<string, string[]>,
  actions: AppRowActions,
): ColumnsType<AppSummary> {
  return [
    // 应用名 + app_key 两行, 与成员单元格同一套排版。
    userColumn<AppSummary>({
      key: "app",
      title: t("appList.column.app"),
      getName: (app) => app.name,
      getUserId: (app) => app.app_key,
    }),
    // owners 存的是用户 ID, 后端按 owner_user_id 精确过滤; 单元格里显示的是拼接后的
    // 名字串, 客户端再按它筛一遍会把后端筛出来的行筛掉, 因此必须过 serverColumn。
    serverColumn(
      textColumn<AppSummary>({
        key: "owners",
        title: t("appList.column.owners"),
        getValue: (app) => safeJoin(app.owners),
        filter: true,
        width: 200,
      }),
      filters.owners,
    ),
    statusColumn<AppSummary>({
      key: "configuration_status",
      title: t("appList.column.configuration"),
      filter: false,
      options: READINESS_VALUES.map((status) => ({
        value: status,
        label: readinessLabel(t, status),
        tone: readinessTone(status),
      })),
      width: 130,
    }),
    // 后端只认单个 status, serverColumn 默认 multiple: false, 下拉即为单选,
    // 不给用户多选却只有一个生效的错觉。
    serverColumn(
      statusColumn<AppSummary>({
        key: "status",
        title: t("common.status"),
        getValue: (app) => (app.is_active ? "active" : "inactive"),
        options: APP_STATUS_VALUES.map((status) => ({
          value: status,
          label: status === "active" ? t("common.enabled") : t("common.disabled"),
          tone: status === "active" ? "evergreen" : "neutral",
        })),
        width: 120,
      }),
      filters.status,
    ),
    dateTimeColumn<AppSummary>({ key: "updated_at", title: t("common.updatedAt"), sorter: false }),
    // 四个按钮(停用/删除/继续接入占位/进入)实测 277px, 加上单元格内边距取 300。
    actionsColumn<AppSummary>({ width: 300, render: (app) => <AppRowActionsCell app={app} actions={actions} /> }),
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
    <>
      <RowActionButton
        type="button"
        variant={app.is_active ? "ghost-danger" : "ghost"}
        disabled={actions.togglePending || !canToggleActive(app)}
        onClick={() => actions.onToggleActive(app)}
      >
        {app.is_active ? t("common.disable") : t("common.enable")}
      </RowActionButton>
      <RowActionButton
        type="button"
        variant="ghost-danger"
        disabled={actions.deletePending || !canDelete(app)}
        onClick={() => actions.onDelete(app)}
      >
        {t("common.delete")}
      </RowActionButton>
      {/* 已就绪的行以 invisible 占位保持每行操作按钮列对齐 */}
      <RowActionLink
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
      </RowActionLink>
      <RowActionLink
        href={enterHref}
        icon={<ArrowRight size={15} />}
        onClick={(event) => {
          event.preventDefault();
          actions.onNavigate(enterHref);
        }}
      >
        {t("common.enter")}
      </RowActionLink>
    </>
  );
}
