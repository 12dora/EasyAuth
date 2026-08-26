import { useQuery } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { PageHeader } from "../../../components/PageHeader";
import { PageState } from "../../../components/ui/PageState";
import { AppTable, type ColumnsType } from "../../../components/antd/AppTable";
import { userColumn } from "../../../components/antd/columns";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { HandoverBlockedAppsPayload } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";
import type { OperationSectionConfig } from "./operationQuery";

type BlockedApp = HandoverBlockedAppsPayload["apps"][number];

/** 未接入应用清单：数据源为 lifecycle/handover-blocked-apps，非 operations 通用列表信封。 */
export function BlockedAppsOperationsSection({ config }: { config: OperationSectionConfig }) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["console", "operations", "blocked-apps"],
    queryFn: () => apiRequest<HandoverBlockedAppsPayload>(config.endpoint),
  });
  const apps = query.data?.apps ?? [];

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t(config.titleKey)}
        description={t("handover.console.blockedApps.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      {query.error && apps.length === 0 ? (
        <PageState
          tone="signal"
          title={t("console.operations.loadFailed")}
          description={(query.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <BlockedAppsTable apps={apps} isLoading={query.isLoading} />
      )}
    </>
  );
}

function BlockedAppsTable({ apps, isLoading }: { apps: BlockedApp[]; isLoading: boolean }) {
  const { t } = useI18n();

  return (
    // 后端一次性返回全部未接入应用, 分页与筛选都在客户端完成。
    <AppTable<BlockedApp>
      columns={blockedAppColumns(t)}
      dataSource={apps}
      emptyTitle={t("handover.console.blockedApps.empty")}
      loading={isLoading}
      // 固定列 220(阻塞交接单数) + 唯一的弹性列(应用)240 -> 460。
      minWidth={460}
      rowKey="app_key"
    />
  );
}

function blockedAppColumns(t: Translator): ColumnsType<BlockedApp> {
  return [
    userColumn<BlockedApp>({
      key: "app",
      title: t("handover.console.blockedApps.column.app"),
      getName: (app) => app.app_name,
      getUserId: (app) => app.app_key,
      filter: true,
    }),
    {
      // 计数徽章没有对应的列预设, 保留旧渲染并补上客户端排序。
      key: "blocked_task_count",
      dataIndex: "blocked_task_count",
      title: t("handover.console.blockedApps.column.blockedTasks"),
      width: 220,
      render: (_value: unknown, app: BlockedApp) => <Badge tone="signal">{app.blocked_task_count}</Badge>,
      sorter: (a: BlockedApp, b: BlockedApp) => a.blocked_task_count - b.blocked_task_count,
    },
  ];
}
