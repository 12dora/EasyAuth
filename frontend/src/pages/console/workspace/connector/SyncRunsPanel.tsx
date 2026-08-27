import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import {
  AppTable,
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
  type ColumnsType,
  type ServerSortState,
} from "../../../../components/antd/AppTable";
import { dateTimeColumn, serverSortColumn, statusColumn, textColumn } from "../../../../components/antd/columns";
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

/** 列 key -> 后端 `ordering` 字段(同步记录接口只认这三个)。 */
const SYNC_RUN_ORDERING_FIELDS = {
  started_at: "started_at",
  trigger: "trigger",
  status: "status",
} as const;

export function SyncRunsPanel({
  appKey,
  instance,
}: {
  appKey: string;
  instance: ConnectorInstanceItem;
}) {
  const { t } = useI18n();
  const serverTable = useServerTable<ConnectorSyncRunItem>({
    defaultPageSize: 10,
    sortParam: ORDERING_PARAM,
    serializeSort: orderingSerializer(SYNC_RUN_ORDERING_FIELDS),
  });
  const sort: ServerSortState = serverTable.query;
  // ordering 必须一起进查询串和查询键, 否则点了表头也不会重新请求。
  const runsSearch = serverTableQuery(serverTable.params);
  const runsQuery = useQuery({
    queryKey: ["console", "app", appKey, "connector-sync-runs", instance.id, runsSearch],
    queryFn: () =>
      apiRequest<ListPayload<ConnectorSyncRunItem>>(
        `/console/api/v1/apps/${appKey}/connectors/${instance.id}/sync-runs?${runsSearch}`,
      ),
    refetchInterval: 30_000,
  });
  const runs = runsQuery.data?.data ?? [];
  serverTable.setTotal(runsQuery.data?.pagination?.total_items);
  // 时间/触发/结果三列在后端排; 统计与错误两列后端排不了, 不给 sorter。
  const columns = useMemo<ColumnsType<ConnectorSyncRunItem>>(
    () => [
      serverSortColumn(
        dateTimeColumn<ConnectorSyncRunItem>({
          key: "started_at",
          title: t("console.connector.runsColumn.time"),
          // 预设自带的时间戳比较函数只会重排当前页, 由 serverSortColumn 换成服务端排序。
          sorter: false,
        }),
        sort,
      ),
      serverSortColumn(
        textColumn<ConnectorSyncRunItem>({
          key: "trigger",
          title: t("console.connector.runsColumn.trigger"),
          getValue: (run) => runTriggerLabel(t, run.trigger),
          width: 120,
        }),
        sort,
      ),
      serverSortColumn(
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
        sort,
      ),
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
    [sort, t],
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
        // 固定列 170(时间) + 120(触发) + 120(结果) + 200(统计) = 610,
        // 唯一的弹性列(错误)留 240 -> 850。
        minWidth={850}
        rowKey="id"
      />
    </PanelSurface>
  );
}
