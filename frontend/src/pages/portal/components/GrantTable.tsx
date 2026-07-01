import type { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";

import { DataTable } from "../../../components/DataTable";
import { StatusBanner } from "../../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { PortalGrant } from "../../../lib/domain";
import { formatDateTime, grantTypeLabel } from "../../../lib/status";

interface PortalGrantGroup {
  key?: string;
  kind?: string;
  name?: string;
}

interface PortalExpandedGrant {
  permission?: string;
  scope?: string;
  source_type?: string;
  source_key?: string;
}

type PortalGrantRow = PortalGrant & {
  groups?: PortalGrantGroup[];
  grants?: PortalExpandedGrant[];
  grant_version?: number | string;
  catalog_version?: number | string;
  snapshot_version?: number | string;
};

export function GrantTable({ endpoint, emptyText }: { endpoint: string; emptyText: string }) {
  const query = useQuery({
    queryKey: ["portal", endpoint],
    queryFn: () => apiRequest<{ items?: PortalGrantRow[]; data?: PortalGrantRow[] }>(endpoint),
  });
  const grants = itemsFromPayload<PortalGrantRow>(query.data);
  const columns: ColumnDef<PortalGrantRow>[] = [
    {
      header: "应用",
      cell: ({ row }) => (
        <div className="table-title">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: "权限组", cell: ({ row }) => formatGroups(row.original.groups) },
    { header: "Expanded Grants", cell: ({ row }) => formatExpandedGrants(row.original.grants) },
    { header: "Source", cell: ({ row }) => formatSources(row.original.grants) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { header: "版本", cell: ({ row }) => formatVersions(row.original) },
    { header: "过期时间", cell: ({ row }) => formatDateTime(row.original.grant_expires_at) },
  ];

  return (
    <>
      {query.error ? <StatusBanner tone="danger" title="授权加载失败" message={(query.error as Error).message} /> : null}
      <DataTable data={grants} columns={columns} emptyText={query.isLoading ? "加载中" : emptyText} />
    </>
  );
}

function formatGroups(groups: PortalGrantGroup[] | undefined): string {
  if (!groups || groups.length === 0) {
    return "-";
  }
  return groups.map((group) => `${group.name ?? group.key ?? "-"} [${group.kind ?? "-"}]`).join("、");
}

function formatExpandedGrants(grants: PortalExpandedGrant[] | undefined): string {
  if (!grants || grants.length === 0) {
    return "-";
  }
  return grants.map((grant) => `${grant.permission ?? "-"}:${grant.scope ?? "-"}`).join("、");
}

function formatSources(grants: PortalExpandedGrant[] | undefined): string {
  if (!grants || grants.length === 0) {
    return "-";
  }
  return grants.map((grant) => (grant.source_key ? `${grant.source_type ?? "-"}:${grant.source_key}` : grant.source_type ?? "-")).join("、");
}

function formatVersions(grant: PortalGrantRow): string {
  if (grant.grant_version === undefined && grant.catalog_version === undefined && grant.snapshot_version === undefined) {
    return grant.version === undefined ? "-" : String(grant.version);
  }
  return `grant ${grant.grant_version ?? "-"} / catalog ${grant.catalog_version ?? "-"} / snapshot ${grant.snapshot_version ?? "-"}`;
}
