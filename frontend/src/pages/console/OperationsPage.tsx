import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
import { useParams } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { DataTable } from "../../components/DataTable";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { OperationRow } from "../../lib/domain";
import { accessRequestStatusLabel, badgeToneForAccessRequestStatus, formatDateTime } from "../../lib/status";

const ENDPOINTS: Record<string, { title: string; endpoint: string }> = {
  "access-requests": { title: "申请运营", endpoint: "/console/api/v1/operations/access-requests" },
  "access-grants": { title: "授权运营", endpoint: "/console/api/v1/operations/access-grants" },
  "dependency-health": { title: "依赖健康", endpoint: "/console/api/v1/operations/dependency-health" },
  audit: { title: "审计日志", endpoint: "/console/api/v1/audit-logs" },
};

export function OperationsPage() {
  const { section = "access-requests" } = useParams();
  const config = ENDPOINTS[section] ?? ENDPOINTS["access-requests"];
  const query = useQuery({
    queryKey: ["console", "operations", section],
    queryFn: () => apiRequest<{ items?: OperationRow[]; data?: OperationRow[] }>(config.endpoint),
  });
  const rows = itemsFromPayload<OperationRow>(query.data);
  const columns = operationColumns(section);

  return (
    <>
      <PageHeader
        eyebrow="Operations"
        title={config.title}
        description="系统管理员的授权运营和依赖观测入口。"
        actions={<Button icon={<RefreshCcw size={16} />} onClick={() => void query.refetch()}>刷新</Button>}
      />
      {query.error ? <StatusBanner tone="danger" title="运营数据加载失败" message={(query.error as Error).message} /> : null}
      <DataTable data={rows} columns={columns} emptyText={query.isLoading ? "加载中" : "暂无数据"} />
    </>
  );
}

function operationColumns(section: string): ColumnDef<OperationRow>[] {
  if (section === "dependency-health") {
    return [
      { header: "组件", cell: ({ row }) => <code>{stringValue(row.original.component)}</code> },
      { header: "状态", cell: ({ row }) => <Badge tone={row.original.status === "healthy" ? "success" : "danger"}>{stringValue(row.original.status)}</Badge> },
      { header: "摘要", cell: ({ row }) => stringValue(row.original.summary) },
      { header: "错误", cell: ({ row }) => stringValue(row.original.error_summary) },
      { header: "检查时间", cell: ({ row }) => formatDateTime(stringValue(row.original.last_checked_at)) },
    ];
  }
  if (section === "access-grants") {
    return [
      { header: "用户", cell: ({ row }) => <code>{stringValue(row.original.user_id)}</code> },
      { header: "应用", cell: ({ row }) => <code>{stringValue(row.original.app_key)}</code> },
      { header: "状态", cell: ({ row }) => <Badge tone={row.original.status === "active" ? "success" : "neutral"}>{stringValue(row.original.status)}</Badge> },
      { header: "类型", cell: ({ row }) => stringValue(row.original.grant_type) },
      { header: "过期时间", cell: ({ row }) => formatDateTime(stringValue(row.original.grant_expires_at)) },
    ];
  }
  return [
    { header: "ID", cell: ({ row }) => row.original.id ?? "-" },
    { header: "用户", cell: ({ row }) => <code>{stringValue(row.original.user_id)}</code> },
    { header: "应用", cell: ({ row }) => <code>{stringValue(row.original.app_key)}</code> },
    { header: "状态", cell: ({ row }) => <Badge tone={badgeToneForAccessRequestStatus(stringValue(row.original.status))}>{accessRequestStatusLabel(stringValue(row.original.status))}</Badge> },
    { header: "类型", cell: ({ row }) => stringValue(row.original.request_type) },
    { header: "提交时间", cell: ({ row }) => formatDateTime(stringValue(row.original.submitted_at)) },
  ];
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value !== "" ? value : "-";
}
