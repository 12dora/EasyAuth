import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
} from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { AppShellOutletContext } from "../../components/AppShell";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow, TableSkeletonRows } from "../../components/ui/TablePrimitives";
import { TablePagination } from "../../components/ui/TablePagination";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { MONO_TEXT_CLASS } from "../../components/ui/tableStyles";

import { Badge } from "../../components/Badge";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest } from "../../lib/api";
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
import {
  parsePortalGrantList,
  parsePortalRequestList,
  type PortalGrantRow,
  type PortalListPayload,
  type PortalRequestRow,
} from "./portalListPayload";

export type PortalView = "grants" | "request" | "requests" | "expiring" | "approvals";

const DEFAULT_PAGE_SIZE = 20;

export function PortalPage({ view }: { view: PortalView }) {
  const { t } = useI18n();
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
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const query = useQuery({
    queryKey: ["portal", endpoint, pagination.pageIndex, pagination.pageSize],
    queryFn: async () =>
      parsePortalGrantList(
        await apiRequest<unknown>(`${endpoint}?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`),
      ),
  });
  const grants = query.data?.data ?? [];
  useClampPage(query.data, setPagination);
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
    manualPagination: true,
    pageCount: query.data?.pagination.total_pages ?? 0,
    state: { pagination },
    onPaginationChange: setPagination,
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
          totalRows={query.data?.pagination.total_items ?? 0}
        />
      )}
    </>
  );
}

function PortalRequestSection() {
  const { t } = useI18n();
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: DEFAULT_PAGE_SIZE });
  const query = useQuery({
    queryKey: ["portal", "requests", pagination.pageIndex, pagination.pageSize],
    queryFn: async () =>
      parsePortalRequestList(
        await apiRequest<unknown>(
          `/portal/api/v1/me/access-requests?page=${pagination.pageIndex + 1}&page_size=${pagination.pageSize}`,
        ),
      ),
  });
  const requests = query.data?.data ?? [];
  useClampPage(query.data, setPagination);
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
          {row.original.decision_comment ? (
            <span className="max-w-64 whitespace-normal text-xs leading-4 text-ink-faint">
              {t("approvals.comment")}：{row.original.decision_comment}（{formatDateTime(row.original.decided_at)}）
            </span>
          ) : null}
        </div>
      ),
    },
    { header: t("common.app"), cell: ({ row }) => row.original.app_name ?? row.original.app_key ?? "-" },
    { header: t("portal.column.groups"), cell: ({ row }) => formatGroups(row.original.authorization_groups) },
    { id: "direct_grants", header: t("portal.column.directGrants"), cell: ({ row }) => formatDirectGrants(row.original.direct_grants) },
    { header: t("portal.column.term"), cell: ({ row }) => grantTypeLabel(t, row.original.grant_type) },
    { header: t("portal.column.expiresAt"), cell: ({ row }) => formatDateTime(row.original.grant_expires_at) },
    { header: t("portal.column.submittedAt"), cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: t("portal.column.reason"), cell: ({ row }) => row.original.reason ?? "-" },
  ];
  const table = useReactTable({
    data: requests,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: query.data?.pagination.total_pages ?? 0,
    state: { pagination },
    onPaginationChange: setPagination,
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
          totalRows={query.data?.pagination.total_items ?? 0}
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
  totalRows,
}: {
  table: ReturnType<typeof useReactTable<T>>;
  columns: ColumnDef<T>[];
  ariaLabel: string;
  isLoading: boolean;
  emptyTitle: string;
  emptyDescription: string;
  totalRows: number;
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
      <TablePagination table={table} totalItems={totalRows} />
    </TableFrame>
  );
}

function isMonoPortalColumn(columnId: string): boolean {
  return ["expanded_grants", "grant_sources", "versions", "direct_grants"].includes(columnId);
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

function useClampPage<T>(payload: PortalListPayload<T> | undefined, setPagination: React.Dispatch<React.SetStateAction<PaginationState>>) {
  const totalPages = payload?.pagination.total_pages;
  useEffect(() => {
    if (totalPages === undefined) {
      return;
    }
    const lastPageIndex = Math.max(0, totalPages - 1);
    setPagination((current) =>
      current.pageIndex > lastPageIndex ? { ...current, pageIndex: lastPageIndex } : current,
    );
  }, [setPagination, totalPages]);
}

function formatGroups(groups: PortalGrantRow["groups"] | PortalRequestRow["authorization_groups"] | undefined): string {
  if (!groups || groups.length === 0) {
    return "-";
  }
  return groups.map((group) => `${group.name ?? group.key ?? "-"} [${group.kind ?? "-"}]`).join("、");
}

function formatExpandedGrants(grants: PortalGrantRow["grants"] | undefined): string {
  if (!grants || grants.length === 0) {
    return "-";
  }
  return grants.map((grant) => `${grant.permission ?? "-"}:${grant.scope ?? "-"}`).join("、");
}

function formatSources(grants: PortalGrantRow["grants"] | undefined): string {
  if (!grants || grants.length === 0) {
    return "-";
  }
  return grants.map((grant) => (grant.source_key ? `${grant.source_type ?? "-"}:${grant.source_key}` : grant.source_type ?? "-")).join("、");
}

function formatVersions(t: Translator, grant: PortalGrantRow): string {
  if (grant.grant_version === undefined && grant.catalog_version === undefined && grant.snapshot_version === undefined) {
    return "-";
  }
  return t("portal.grant.versions", {
    grant: grant.grant_version ?? "-",
    catalog: grant.catalog_version ?? "-",
    snapshot: grant.snapshot_version ?? "-",
  });
}

function formatDirectGrants(directGrants: PortalRequestRow["direct_grants"] | undefined): string {
  if (!directGrants || directGrants.length === 0) {
    return "-";
  }
  return directGrants
    .map((grant) => `${grant.permission_name ?? grant.permission ?? "-"} (${grant.permission ?? "-"}):${grant.scope ?? "-"}`)
    .join("、");
}
