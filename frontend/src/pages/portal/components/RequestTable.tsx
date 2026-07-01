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

interface PortalRequestGroup {
  key?: string;
  kind?: string;
  name?: string;
}

interface PortalRequestDirectGrant {
  permission?: string;
  permission_name?: string;
  scope?: string;
}

type PortalRequestRow = PortalRequest & {
  authorization_groups?: PortalRequestGroup[];
  direct_grants?: PortalRequestDirectGrant[];
};

export function RequestTable() {
  const query = useQuery({
    queryKey: ["portal", "requests"],
    queryFn: () => apiRequest<{ items?: PortalRequestRow[]; data?: PortalRequestRow[] }>("/portal/api/v1/me/access-requests"),
  });
  const requests = itemsFromPayload<PortalRequestRow>(query.data);
  const columns: ColumnDef<PortalRequestRow>[] = [
    {
      header: "状态",
      cell: ({ row }) => (
        <Badge tone={badgeToneForAccessRequestStatus(row.original.status)}>
          {row.original.status_label ?? accessRequestStatusLabel(row.original.status)}
        </Badge>
      ),
    },
    { header: "应用", cell: ({ row }) => row.original.app_name ?? row.original.app_key ?? "-" },
    { header: "权限组", cell: ({ row }) => formatGroups(row.original.authorization_groups) },
    { header: "Direct Grants", cell: ({ row }) => formatDirectGrants(row.original.direct_grants) },
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

function formatGroups(groups: PortalRequestGroup[] | undefined): string {
  if (!groups || groups.length === 0) {
    return "-";
  }
  return groups.map((group) => `${group.name ?? group.key ?? "-"} [${group.kind ?? "-"}]`).join("、");
}

function formatDirectGrants(directGrants: PortalRequestDirectGrant[] | undefined): string {
  if (!directGrants || directGrants.length === 0) {
    return "-";
  }
  return directGrants
    .map((grant) => `${grant.permission_name ?? grant.permission ?? "-"} (${grant.permission ?? "-"}):${grant.scope ?? "-"}`)
    .join("、");
}
