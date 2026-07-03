import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
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
import type { OperationRow } from "../../lib/domain";
import { useI18n } from "../../i18n/I18nProvider";
import { accessRequestStatusLabel, badgeToneForAccessRequestStatus, formatDateTime } from "../../lib/status";
import type { Translator } from "../../lib/status";

const ENDPOINTS: Record<string, { title: string; endpoint: string }> = {
  "access-requests": { title: "申请运营", endpoint: "/console/api/v1/operations/access-requests" },
  "access-grants": { title: "授权运营", endpoint: "/console/api/v1/operations/access-grants" },
  "dependency-health": { title: "依赖健康", endpoint: "/console/api/v1/operations/dependency-health" },
  audit: { title: "审计日志", endpoint: "/console/api/v1/audit-logs" },
};

export function OperationsPage() {
  const { t } = useI18n();
  const { section = "access-requests" } = useParams();
  const config = ENDPOINTS[section] ?? ENDPOINTS["access-requests"];
  const query = useQuery({
    queryKey: ["console", "operations", section],
    queryFn: () => apiRequest<{ items?: OperationRow[]; data?: OperationRow[] }>(config.endpoint),
  });
  const rows = itemsFromPayload<OperationRow>(query.data);
  const columns = operationColumns(section, t);
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <>
      <PageHeader
        eyebrow="运营"
        title={config.title}
        description="系统管理员的授权运营和依赖观测入口。"
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
            刷新
          </Button>
        }
      />
      {query.error && rows.length > 0 ? (
        <StatusBanner tone="signal" title="运营数据加载失败" message={(query.error as Error).message} />
      ) : null}
      {query.error && rows.length === 0 ? (
        <PageState
          tone="signal"
          title="运营数据加载失败"
          description={(query.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              重新加载
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
                  <EmptyState title="暂无运营数据" description="当前筛选下没有可展示的记录。" />
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
      { header: "组件", cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.component)}</code> },
      { header: "状态", cell: ({ row }) => <Badge tone={row.original.status === "healthy" ? "evergreen" : "signal"}>{stringValue(row.original.status)}</Badge> },
      { header: "摘要", cell: ({ row }) => stringValue(row.original.summary) },
      { header: "错误", cell: ({ row }) => stringValue(row.original.error_summary) },
      { header: "检查时间", cell: ({ row }) => formatDateTime(stringValue(row.original.last_checked_at)) },
    ];
  }
  if (section === "access-grants") {
    return [
      { header: "用户", cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
      { header: "应用", cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
      { header: "状态", cell: ({ row }) => <Badge tone={row.original.status === "active" ? "evergreen" : "neutral"}>{stringValue(row.original.status)}</Badge> },
      { header: "类型", cell: ({ row }) => stringValue(row.original.grant_type) },
      { header: "过期时间", cell: ({ row }) => formatDateTime(stringValue(row.original.grant_expires_at)) },
    ];
  }
  return [
    { header: "ID", cell: ({ row }) => row.original.id ?? "-" },
    { header: "用户", cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
    { header: "应用", cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
    { header: "状态", cell: ({ row }) => <Badge tone={badgeToneForAccessRequestStatus(stringValue(row.original.status))}>{accessRequestStatusLabel(t, stringValue(row.original.status))}</Badge> },
    { header: "类型", cell: ({ row }) => stringValue(row.original.request_type) },
    { header: "提交时间", cell: ({ row }) => formatDateTime(stringValue(row.original.submitted_at)) },
  ];
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value !== "" ? value : "-";
}
