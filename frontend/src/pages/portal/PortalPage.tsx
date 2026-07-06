import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useOutletContext } from "react-router-dom";

import type { AppShellOutletContext } from "../../components/AppShell";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TablePagination } from "../../components/ui/TablePagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { ListPayload } from "../../lib/api";
import type { PortalGrant, PortalRequest } from "../../lib/domain";
import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../lib/status";
import type { Translator } from "../../lib/status";
import { useI18n } from "../../i18n/I18nProvider";
import { AccessRequestForm } from "./components/AccessRequestForm";
import { PortalApprovalsSection } from "./components/PortalApprovalsSection";

type PortalView = "grants" | "request" | "requests" | "expiring" | "approvals";

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
  const { t } = useI18n();
  const location = useLocation();
  const view = portalViewFromPath(location.pathname);
  const outletContext = useOutletContext<AppShellOutletContext | null>();
  const currentUserId = outletContext?.currentUserId ?? "";

  return (
    <>
      <PageHeader eyebrow={t("portal.eyebrow")} title={viewTitle(t, view)} />
      {view === "grants" ? <PortalGrantSection endpoint="/portal/api/v1/me/grants" emptyText={t("portal.grants.emptyCurrent")} /> : null}
      {view === "expiring" ? <PortalGrantSection endpoint="/portal/api/v1/me/grants/expiring" emptyText={t("portal.grants.emptyExpiring")} /> : null}
      {view === "requests" ? <PortalRequestSection /> : null}
      {view === "request" ? <AccessRequestForm currentUserId={currentUserId} /> : null}
      {view === "approvals" ? <PortalApprovalsSection /> : null}
    </>
  );
}

function PortalGrantSection({ endpoint, emptyText }: { endpoint: string; emptyText: string }) {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["portal", endpoint],
    queryFn: () => apiRequest<ListPayload<PortalGrantRow>>(endpoint),
  });
  const grants = itemsFromPayload<PortalGrantRow>(query.data);
  const columns: ColumnDef<PortalGrantRow>[] = [
    {
      header: t("common.app"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: t("portal.column.groups"), cell: ({ row }) => formatGroups(row.original.groups) },
    { id: "expanded_grants", header: t("portal.column.expandedGrants"), cell: ({ row }) => formatExpandedGrants(row.original.grants) },
    { id: "grant_sources", header: t("common.source"), cell: ({ row }) => formatSources(row.original.grants) },
    { header: t("portal.column.term"), cell: ({ row }) => grantTypeLabel(t, row.original.grant_type) },
    { id: "versions", header: t("portal.column.versions"), cell: ({ row }) => formatVersions(t, row.original) },
    { header: t("portal.column.expiresAt"), cell: ({ row }) => formatDateTime(row.original.grant_expires_at) },
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
        <StatusBanner tone="signal" title={t("portal.grants.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {query.error && grants.length === 0 ? (
        <PageState tone="signal" title={t("portal.grants.loadFailed")} description={(query.error as Error).message} />
      ) : (
        <PortalTable
          table={table}
          columns={columns}
          ariaLabel={t("portal.grants.ariaLabel")}
          isLoading={query.isLoading}
          emptyTitle={emptyText}
          emptyDescription={t("portal.grants.emptyDescription")}
        />
      )}
    </>
  );
}

function PortalRequestSection() {
  const { t } = useI18n();
  const query = useQuery({
    queryKey: ["portal", "requests"],
    queryFn: () => apiRequest<ListPayload<PortalRequestRow>>("/portal/api/v1/me/access-requests"),
  });
  const requests = itemsFromPayload<PortalRequestRow>(query.data);
  const columns: ColumnDef<PortalRequestRow>[] = [
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <span>
            <Badge tone={badgeToneForAccessRequestStatus(row.original.status)}>
              {row.original.status_label ?? accessRequestStatusLabel(t, row.original.status)}
            </Badge>
          </span>
          {row.original.status === "rejected" && row.original.decision_comment ? (
            <span className="max-w-64 whitespace-normal text-xs leading-4 text-ink-faint">
              {t("portal.requests.rejectedInfo", {
                comment: row.original.decision_comment,
                time: formatDateTime(row.original.decided_at),
              })}
            </span>
          ) : null}
        </div>
      ),
    },
    { header: t("common.app"), cell: ({ row }) => row.original.app_name ?? row.original.app_key ?? "-" },
    { header: t("portal.column.groups"), cell: ({ row }) => formatGroups(row.original.authorization_groups) },
    { id: "direct_grants", header: t("portal.column.directGrants"), cell: ({ row }) => formatDirectGrants(row.original.direct_grants) },
    { header: t("portal.column.term"), cell: ({ row }) => grantTypeLabel(t, row.original.grant_type) },
    { header: t("portal.column.submittedAt"), cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: t("portal.column.reason"), cell: ({ row }) => row.original.reason ?? "-" },
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
        <StatusBanner tone="signal" title={t("portal.requests.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {query.error && requests.length === 0 ? (
        <PageState tone="signal" title={t("portal.requests.loadFailed")} description={(query.error as Error).message} />
      ) : (
        <PortalTable
          table={table}
          columns={columns}
          ariaLabel={t("nav.portal.myRequests")}
          isLoading={query.isLoading}
          emptyTitle={t("portal.requests.empty")}
          emptyDescription={t("portal.requests.emptyDescription")}
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
  if (pathname.endsWith("/approvals")) {
    return "approvals";
  }
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

function viewTitle(t: Translator, view: PortalView): string {
  switch (view) {
    case "request":
      return t("nav.portal.requestAccess");
    case "requests":
      return t("nav.portal.myRequests");
    case "expiring":
      return t("nav.portal.expiring");
    case "approvals":
      return t("nav.portal.myApprovals");
    default:
      return t("nav.portal.myPermissions");
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

function formatVersions(t: Translator, grant: PortalGrantRow): string {
  if (grant.grant_version === undefined && grant.catalog_version === undefined && grant.snapshot_version === undefined) {
    return grant.version === undefined ? "-" : String(grant.version);
  }
  return t("portal.grant.versions", {
    grant: grant.grant_version ?? "-",
    catalog: grant.catalog_version ?? "-",
    snapshot: grant.snapshot_version ?? "-",
  });
}

function formatDirectGrants(directGrants: PortalRequestDirectGrant[] | undefined): string {
  if (!directGrants || directGrants.length === 0) {
    return "-";
  }
  return directGrants
    .map((grant) => `${grant.permission_name ?? grant.permission ?? "-"} (${grant.permission ?? "-"}):${grant.scope ?? "-"}`)
    .join("、");
}
