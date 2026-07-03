import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TablePagination } from "../../components/ui/TablePagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { PortalGrant, PortalRequest } from "../../lib/domain";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../lib/status";
import { AccessRequestForm } from "./components/AccessRequestForm";

type PortalView = "grants" | "request" | "requests" | "expiring";

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

export function PortalPage() {
  const location = useLocation();
  const view = portalViewFromPath(location.pathname);

  return (
    <>
      <PageHeader eyebrow="门户" title={viewTitle(view)} />
      {view === "grants" ? <PortalGrantSection endpoint="/portal/api/v1/me/grants" emptyText="暂无当前授权" /> : null}
      {view === "expiring" ? <PortalGrantSection endpoint="/portal/api/v1/me/grants/expiring" emptyText="暂无即将过期授权" /> : null}
      {view === "requests" ? <PortalRequestSection /> : null}
      {view === "request" ? <AccessRequestForm /> : null}
    </>
  );
}

function PortalGrantSection({ endpoint, emptyText }: { endpoint: string; emptyText: string }) {
  const query = useQuery({
    queryKey: ["portal", endpoint],
    queryFn: () => apiRequest<{ items?: PortalGrantRow[]; data?: PortalGrantRow[] }>(endpoint),
  });
  const grants = itemsFromPayload<PortalGrantRow>(query.data);
  const columns: ColumnDef<PortalGrantRow>[] = [
    {
      header: "应用",
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: "权限组", cell: ({ row }) => formatGroups(row.original.groups) },
    { id: "expanded_grants", header: "展开授权", cell: ({ row }) => formatExpandedGrants(row.original.grants) },
    { id: "grant_sources", header: "来源", cell: ({ row }) => formatSources(row.original.grants) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { id: "versions", header: "版本", cell: ({ row }) => formatVersions(row.original) },
    { header: "过期时间", cell: ({ row }) => formatDateTime(row.original.grant_expires_at) },
  ];
  const table = useReactTable({
    data: grants,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <>
      {query.error && grants.length > 0 ? (
        <StatusBanner tone="signal" title="授权加载失败" message={(query.error as Error).message} />
      ) : null}
      {query.error && grants.length === 0 ? (
        <PageState tone="signal" title="授权加载失败" description={(query.error as Error).message} />
      ) : (
        <PortalTable
          table={table}
          columns={columns}
          ariaLabel="我的授权"
          isLoading={query.isLoading}
          emptyTitle={emptyText}
          emptyDescription="当前视图没有可展示的授权记录。"
        />
      )}
    </>
  );
}

function PortalRequestSection() {
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
    { id: "direct_grants", header: "直接授权", cell: ({ row }) => formatDirectGrants(row.original.direct_grants) },
    { header: "期限", cell: ({ row }) => grantTypeLabel(row.original.grant_type) },
    { header: "提交时间", cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: "原因", cell: ({ row }) => row.original.reason ?? "-" },
  ];
  const table = useReactTable({
    data: requests,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <>
      {query.error && requests.length > 0 ? (
        <StatusBanner tone="signal" title="申请记录加载失败" message={(query.error as Error).message} />
      ) : null}
      {query.error && requests.length === 0 ? (
        <PageState tone="signal" title="申请记录加载失败" description={(query.error as Error).message} />
      ) : (
        <PortalTable
          table={table}
          columns={columns}
          ariaLabel="我的申请"
          isLoading={query.isLoading}
          emptyTitle="暂无申请记录"
          emptyDescription="当前账号还没有提交过权限申请。"
        />
      )}
    </>
  );
}

function PortalTable<T>({
  table,
  columns,
  ariaLabel,
  isLoading,
  emptyTitle,
  emptyDescription,
}: {
  table: ReturnType<typeof useReactTable<T>>;
  columns: ColumnDef<T>[];
  ariaLabel: string;
  isLoading: boolean;
  emptyTitle: string;
  emptyDescription: string;
}) {
  return (
    <TableFrame>
      <TableRoot aria-label={ariaLabel}>
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
          {isLoading ? (
            <TableSkeletonRows columns={columns.length} />
          ) : table.getRowModel().rows.length > 0 ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className={isMonoPortalColumn(cell.column.id) ? MONO_TEXT_CLASS : undefined}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={columns.length}>
              <EmptyState title={emptyTitle} description={emptyDescription} />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} />
    </TableFrame>
  );
}

function isMonoPortalColumn(columnId: string): boolean {
  return ["expanded_grants", "grant_sources", "versions", "direct_grants"].includes(columnId);
}

function portalViewFromPath(pathname: string): PortalView {
  if (pathname.endsWith("/request")) {
    return "request";
  }
  if (pathname.endsWith("/requests")) {
    return "requests";
  }
  if (pathname.endsWith("/expiring")) {
    return "expiring";
  }
  return "grants";
}

function viewTitle(view: PortalView): string {
  switch (view) {
    case "request":
      return "申请权限";
    case "requests":
      return "我的申请";
    case "expiring":
      return "即将过期";
    default:
      return "我的权限";
  }
}

function formatGroups(groups: PortalGrantGroup[] | PortalRequestGroup[] | undefined): string {
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
  return `授权 ${grant.grant_version ?? "-"} / 目录 ${grant.catalog_version ?? "-"} / 快照 ${grant.snapshot_version ?? "-"}`;
}

function formatDirectGrants(directGrants: PortalRequestDirectGrant[] | undefined): string {
  if (!directGrants || directGrants.length === 0) {
    return "-";
  }
  return directGrants
    .map((grant) => `${grant.permission_name ?? grant.permission ?? "-"} (${grant.permission ?? "-"}):${grant.scope ?? "-"}`)
    .join("、");
}
