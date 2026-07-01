import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../../components/Badge";
import { DataTable } from "../../../components/DataTable";
import { StatusBanner } from "../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { PortalRequest } from "../../../lib/domain";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../../lib/status";

export function RequestTable() {
  const query = useQuery({
    queryKey: ["portal", "requests"],
    queryFn: () => apiRequest<{ items?: PortalRequest[]; data?: PortalRequest[] }>("/portal/api/v1/me/access-requests"),
  });
  const requests = itemsFromPayload<PortalRequest>(query.data);
  const columns: ColumnDef<PortalRequest>[] = [
    {
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={badgeToneForAccessRequestStatus(row.original.status)}>
          {row.original.status_label ?? accessRequestStatusLabel(row.original.status)}
        </Badge>
      ),
    },
    { header: "应用", cell: ({ row }) => row.original.app_name ?? row.original.app_key ?? "-" },
    { header: "角色", cell: ({ row }) => join(row.original.role_names ?? row.original.roles) },
    { header: "权限", cell: ({ row }) => join(row.original.permissions) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { header: "提交时间", cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: "原因", cell: ({ row }) => row.original.reason ?? "-" },
  ];

  return (
    <>
      {query.error ? <StatusBanner tone="danger" title="申请记录加载失败" message={(query.error as Error).message} /> : null}
      <DataTable data={requests} columns={columns} emptyText={query.isLoading ? "加载中" : "暂无申请记录"} />
    </>
  );
}

function join(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}
