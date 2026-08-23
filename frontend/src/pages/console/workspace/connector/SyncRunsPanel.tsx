import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge } from "../../../../components/Badge";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PaginationBar } from "../../../../components/ui/PaginationBar";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import {
  TableBody,
  TableCell,
  TableEmptyRow,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
} from "../../../../components/ui/TablePrimitives";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { ListPayload } from "../../../../lib/api";
import type {
  ConnectorInstanceItem,
  ConnectorSyncRunItem,
} from "../../../../lib/domain";
import { formatDateTime } from "../../../../lib/status";
import {
  RUN_STATUS_TONES,
  formatRunStats,
  runStatusLabel,
  runTriggerLabel,
  syncRunsPageView,
} from "./connectorFormat";

export function SyncRunsPanel({
  appKey,
  instance,
}: {
  appKey: string;
  instance: ConnectorInstanceItem;
}) {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
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
  const view = syncRunsPageView(
    runsQuery.data?.pagination,
    page,
    pageSize,
    runs.length,
  );

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <h3 className="text-base font-semibold text-ink">
        {t("console.connector.runsHeading")}
      </h3>
      <TableFrame>
        <TableRoot>
          <SyncRunsTableHead />
          <TableBody>
            {runs.length === 0 ? (
              <TableEmptyRow colSpan={5}>
                <EmptyState title={t("console.connector.runsEmpty")} />
              </TableEmptyRow>
            ) : (
              runs.map((run) => <SyncRunRow key={run.id} run={run} />)
            )}
          </TableBody>
        </TableRoot>
        <PaginationBar
          pageStart={view.pageStart}
          pageEnd={view.pageEnd}
          totalRows={view.totalRows}
          pageSize={view.effectivePageSize}
          pageIndex={view.pageIndex}
          pageCount={view.pageCount}
          canPreviousPage={view.pageIndex > 0}
          canNextPage={view.pageIndex + 1 < view.pageCount}
          onPageSizeChange={(nextPageSize) => {
            setPage(1);
            setPageSize(nextPageSize);
          }}
          onPreviousPage={() => setPage((current) => Math.max(1, current - 1))}
          onNextPage={() => setPage((current) => current + 1)}
        />
      </TableFrame>
    </PanelSurface>
  );
}

function SyncRunsTableHead() {
  const { t } = useI18n();

  return (
    <TableHead>
      <TableRow>
        <TableHeaderCell>
          {t("console.connector.runsColumn.time")}
        </TableHeaderCell>
        <TableHeaderCell>
          {t("console.connector.runsColumn.trigger")}
        </TableHeaderCell>
        <TableHeaderCell>
          {t("console.connector.runsColumn.status")}
        </TableHeaderCell>
        <TableHeaderCell>
          {t("console.connector.runsColumn.stats")}
        </TableHeaderCell>
        <TableHeaderCell>
          {t("console.connector.runsColumn.error")}
        </TableHeaderCell>
      </TableRow>
    </TableHead>
  );
}

function SyncRunRow({ run }: { run: ConnectorSyncRunItem }) {
  const { t } = useI18n();

  return (
    <TableRow>
      <TableCell>{formatDateTime(run.started_at)}</TableCell>
      <TableCell>{runTriggerLabel(t, run.trigger)}</TableCell>
      <TableCell>
        <Badge tone={RUN_STATUS_TONES[run.status] ?? "neutral"}>
          {runStatusLabel(t, run.status)}
        </Badge>
      </TableCell>
      <TableCell>
        <code className="text-xs text-ink-soft">{formatRunStats(run.stats)}</code>
      </TableCell>
      <TableCell>
        <span className="text-xs text-ink-soft">{run.error || "-"}</span>
      </TableCell>
    </TableRow>
  );
}
