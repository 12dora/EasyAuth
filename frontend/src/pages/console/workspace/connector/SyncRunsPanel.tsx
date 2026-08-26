import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { AppTable, useServerTable, type ColumnsType } from "../../../../components/antd/AppTable";
import { dateTimeColumn, statusColumn, textColumn } from "../../../../components/antd/columns";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type {
  ConnectorInstanceItem,
  ConnectorSyncRunItem,
} from "../../../../lib/domain";
import {
  RUN_STATUS_TONES,
  formatRunStats,
  runStatusLabel,
  runTriggerLabel,
} from "./connectorFormat";

const RUN_STATUSES = ["success", "partial", "failed"] as const;

export function SyncRunsPanel({
  appKey,
  instance,
}: {
  appKey: string;
  instance: ConnectorInstanceItem;
}) {
  const { t } = useI18n();
  // 后端只支持 page/page_size, 没有排序参数: serializeSort 置空,
  // 表头排序退化为 antd 对当前页的客户端排序。
  const serverTable = useServerTable<ConnectorSyncRunItem>({
    defaultPageSize: 10,
    serializeSort: () => ({}),
  });
  const { page, page_size: pageSize } = serverTable.params;
  const runsQuery = useQuery({
    queryKey: [
      "console",
      "app",
      appKey,
      "connector-sync-runs",
      instance.id,
      page,
      pageSize,
    ],
    queryFn: () =>
      apiRequest<ListPayload<ConnectorSyncRunItem>>(
        `/console/api/v1/apps/${appKey}/connectors/${instance.id}/sync-runs?page=${page}&page_size=${pageSize}`,
      ),
    refetchInterval: 30_000,
  });
  const runs = runsQuery.data?.data ?? [];
  serverTable.setTotal(runsQuery.data?.pagination?.total_items);
  const columns = useMemo<ColumnsType<ConnectorSyncRunItem>>(
    () => [
      dateTimeColumn<ConnectorSyncRunItem>({
        key: "started_at",
        title: t("console.connector.runsColumn.time"),
      }),
      textColumn<ConnectorSyncRunItem>({
        key: "trigger",
        title: t("console.connector.runsColumn.trigger"),
        getValue: (run) => runTriggerLabel(t, run.trigger),
        sorter: true,
        width: 120,
      }),
      statusColumn<ConnectorSyncRunItem>({
        key: "status",
        title: t("console.connector.runsColumn.status"),
        options: RUN_STATUSES.map((status) => ({
          value: status,
          label: runStatusLabel(t, status),
          tone: RUN_STATUS_TONES[status],
        })),
        // 后端不支持按结果过滤, 只对当前页过滤会与「共 N 条」自相矛盾。
        filter: false,
        width: 120,
      }),
      textColumn<ConnectorSyncRunItem>({
        key: "stats",
        title: t("console.connector.runsColumn.stats"),
        getValue: (run) => formatRunStats(run.stats),
        mono: true,
        width: 200,
      }),
      textColumn<ConnectorSyncRunItem>({
        key: "error",
        title: t("console.connector.runsColumn.error"),
      }),
    ],
    [t],
  );

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <h3 className="text-base font-semibold text-ink">
        {t("console.connector.runsHeading")}
      </h3>
      <AppTable<ConnectorSyncRunItem>
        {...serverTable.tableProps}
        columns={columns}
        dataSource={runs}
        emptyTitle={t("console.connector.runsEmpty")}
        loading={runsQuery.isLoading}
        rowKey="id"
      />
    </PanelSurface>
  );
}
