import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TablePagination } from "../../components/ui/TablePagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { ListPayload } from "../../lib/api";
import type { OperationRow } from "../../lib/domain";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/messages";
import { accessRequestStatusLabel, badgeToneForAccessRequestStatus, formatDateTime } from "../../lib/status";
import type { Translator } from "../../lib/status";

const ENDPOINTS: Record<string, { titleKey: MessageKey; endpoint: string }> = {
  "access-requests": { titleKey: "nav.console.accessRequests", endpoint: "/console/api/v1/operations/access-requests" },
  "access-grants": { titleKey: "nav.console.accessGrants", endpoint: "/console/api/v1/operations/access-grants" },
  "dependency-health": { titleKey: "nav.console.dependencyHealth", endpoint: "/console/api/v1/operations/dependency-health" },
  audit: { titleKey: "console.operations.title.audit", endpoint: "/console/api/v1/audit-logs" },
};

const DEFAULT_PAGE_SIZE = 20;

export function OperationsPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { section = "access-requests" } = useParams();
  const config = ENDPOINTS[section] ?? ENDPOINTS["access-requests"];
  // 依赖健康返回非分页的 list_payload; 其余分区走后端分页, 需按分区区分表格模式。
  const isPaginated = section !== "dependency-health";
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });

  // 切换分区时回到第一页, 避免带着上个分区的页码请求。
  useEffect(() => {
    setPagination((current) => (current.pageIndex === 0 ? current : { ...current, pageIndex: 0 }));
  }, [section]);

  const query = useQuery({
    queryKey: isPaginated
      ? ["console", "operations", section, pagination.pageIndex, pagination.pageSize]
      : ["console", "operations", section],
    queryFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        isPaginated ? `${config.endpoint}?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}` : config.endpoint,
      ),
  });
  const healthCheckMutation = useMutation({
    mutationFn: () =>
      apiRequest<ListPayload<OperationRow>>(
        "/console/api/v1/operations/dependency-health/checks",
        { method: "POST" },
      ),
    onSuccess: (payload) => {
      queryClient.setQueryData(["console", "operations", "dependency-health"], payload);
    },
  });
  const rows = itemsFromPayload<OperationRow>(query.data);
  const columns = operationColumns(section, t);
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    ...(isPaginated
      ? {
          manualPagination: true as const,
          pageCount: query.data?.pagination?.total_pages ?? 1,
          state: { pagination },
          onPaginationChange: setPagination,
        }
      : {
          getPaginationRowModel: getPaginationRowModel(),
        }),
  });

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t(config.titleKey)}
        description={t("console.operations.description")}
        actions={
          <>
            {section === "dependency-health" ? (
              <Button
                variant="primary"
                icon={<Activity size={16} />}
                loading={healthCheckMutation.isPending}
                onClick={() => healthCheckMutation.mutate()}
              >
                {t("ops.dependencyHealth.runCheck")}
              </Button>
            ) : null}
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.refresh")}
            </Button>
          </>
        }
      />
      {healthCheckMutation.error ? (
        <StatusBanner
          tone="signal"
          title={t("ops.dependencyHealth.runCheckFailed")}
          message={(healthCheckMutation.error as Error).message}
        />
      ) : null}
      {query.error && rows.length > 0 ? (
        <StatusBanner tone="signal" title={t("console.operations.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {query.error && rows.length === 0 ? (
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
        <TableFrame>
          <TableRoot>
            <TableHead>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHeaderCell key={header.id}>
                      {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHeaderCell>
                  ))}
                </TableRow>
              ))}
            </TableHead>
            <TableBody>
              {query.isLoading ? (
                <TableSkeletonRows columns={table.getAllLeafColumns().length} />
              ) : table.getRowModel().rows.length > 0 ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow key={row.id}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
                  <EmptyState title={t("console.operations.empty")} description={t("console.operations.emptyDescription")} />
                </TableEmptyRow>
              )}
            </TableBody>
          </TableRoot>
          <TablePagination table={table} />
        </TableFrame>
      )}
    </>
  );
}

function operationColumns(section: string, t: Translator): ColumnDef<OperationRow>[] {
  if (section === "dependency-health") {
    return [
      { header: t("console.operations.column.component"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.component)}</code> },
      { header: t("common.status"), cell: ({ row }) => <Badge tone={healthTone(stringValue(row.original.status))}>{stringValue(row.original.status)}</Badge> },
      { header: t("console.operations.column.summary"), cell: ({ row }) => stringValue(row.original.summary) },
      { header: t("console.operations.column.error"), cell: ({ row }) => stringValue(row.original.error_summary) },
      { header: t("console.operations.column.checkedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.last_checked_at)) },
    ];
  }
  if (section === "audit") {
    // 审计行字段对齐后端 audit_api._audit_item; 审计行无 id, 故不展示 ID 列。
    return [
      { header: t("console.operations.column.event"), cell: ({ row }) => stringValue(row.original.event_type) },
      { header: t("console.operations.column.actor"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditPair(row.original.actor_type, row.original.actor_id)}</code> },
      { header: t("console.operations.column.target"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditPair(row.original.target_type, row.original.target_id)}</code> },
      { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditAppKey(row.original)}</code> },
      { header: t("console.operations.column.time"), cell: ({ row }) => formatDateTime(stringValue(row.original.created_at)) },
    ];
  }
  if (section === "access-grants") {
    return [
      { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
      { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
      { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.status === "active" ? "evergreen" : "neutral"}>{stringValue(row.original.status)}</Badge> },
      { header: t("common.type"), cell: ({ row }) => stringValue(row.original.grant_type) },
      { header: t("console.operations.column.expiresAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.grant_expires_at)) },
    ];
  }
  return [
    { header: "ID", cell: ({ row }) => row.original.id ?? "-" },
    { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
    { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={badgeToneForAccessRequestStatus(stringValue(row.original.status))}>{accessRequestStatusLabel(t, stringValue(row.original.status))}</Badge> },
    { header: t("common.type"), cell: ({ row }) => stringValue(row.original.request_type) },
    { header: t("console.operations.column.submittedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.submitted_at)) },
  ];
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value !== "" ? value : "-";
}

function auditPair(type: string | undefined, id: string | undefined): string {
  const parts = [type, id].filter((part): part is string => typeof part === "string" && part !== "");
  return parts.length > 0 ? parts.join(":") : "-";
}

function auditAppKey(row: OperationRow): string {
  // 非超管审计以 metadata.app_key 做作用域, app_key 不在顶层字段而在 metadata 中。
  const appKey = row.metadata && typeof row.metadata === "object" ? row.metadata.app_key : undefined;
  return typeof appKey === "string" && appKey !== "" ? appKey : "-";
}

function healthTone(status: string): "evergreen" | "amber" | "neutral" | "signal" {
  if (status === "healthy") {
    return "evergreen";
  }
  if (status === "warning") {
    return "amber";
  }
  if (status === "unknown") {
    return "neutral";
  }
  return "signal";
}
