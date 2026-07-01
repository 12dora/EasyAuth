import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";

import { DataTable } from "../../../components/DataTable";
import { StatusBanner } from "../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { PortalGrant } from "../../../lib/domain";
import { formatDateTime, grantTypeLabel } from "../../../lib/status";

export function GrantTable({ endpoint, emptyText }: { endpoint: string; emptyText: string }) {
  const query = useQuery({
    queryKey: ["portal", endpoint],
    queryFn: () => apiRequest<{ items?: PortalGrant[]; data?: PortalGrant[] }>(endpoint),
  });
  const grants = itemsFromPayload<PortalGrant>(query.data);
  const columns: ColumnDef<PortalGrant>[] = [
    {
      header: "应用",
      cell: ({ row }) => (
        <div className="table-title">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: "角色", cell: ({ row }) => join(row.original.role_names ?? row.original.roles) },
    { header: "权限", cell: ({ row }) => join(row.original.permissions) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { header: "版本", cell: ({ row }) => row.original.version ?? "-" },
    { header: "过期时间", cell: ({ row }) => formatDateTime(row.original.grant_expires_at) },
  ];

  return (
    <>
      {query.error ? <StatusBanner tone="danger" title="授权加载失败" message={(query.error as Error).message} /> : null}
      <DataTable data={grants} columns={columns} emptyText={query.isLoading ? "加载中" : emptyText} />
    </>
  );
}

function join(values: string[] | undefined): string {
  return values && values.length > 0 ? values.join("、") : "-";
}
