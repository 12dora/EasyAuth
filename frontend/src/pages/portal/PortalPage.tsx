import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { AppShellOutletContext } from "../../components/AppShell";
import { AppTable, useServerTable, type ColumnsType } from "../../components/antd/AppTable";
import { MONO_TEXT_CLASS, actionsColumn, dateTimeColumn, textColumn } from "../../components/antd/columns";
import { PageState } from "../../components/ui/PageState";


import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
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
import { PortalPreOffboardDialog } from "./PortalPreOffboardDialog";
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
  const [preOffboardOpen, setPreOffboardOpen] = useState(false);

  return (
    <>
      <PageHeader
        eyebrow={t("portal.eyebrow")}
        title={viewTitle(t, view)}
        actions={
          view === "grants" ? (
            <Button type="button" variant="ghost" onClick={() => setPreOffboardOpen(true)}>
              {t("handover.portal.list.preOffboard")}
            </Button>
          ) : undefined
        }
      />
      {view === "grants" ? <PortalGrantSection endpoint="/portal/api/v1/me/grants" emptyText={t("portal.grants.emptyCurrent")} /> : null}
      {view === "expiring" ? <PortalGrantSection endpoint="/portal/api/v1/me/grants/expiring" emptyText={t("portal.grants.emptyExpiring")} /> : null}
      {view === "requests" ? <PortalRequestSection /> : null}
      {view === "request" ? <AccessRequestForm currentUserId={currentUserId} /> : null}
      {view === "approvals" ? <PortalApprovalsSection /> : null}
      {preOffboardOpen ? <PortalPreOffboardDialog onClose={() => setPreOffboardOpen(false)} /> : null}
    </>
  );
}

function PortalGrantSection({ endpoint, emptyText }: { endpoint: string; emptyText: string }) {
  const { t } = useI18n();
  // 门户授权列表只支持 page/page_size: serializeSort 置空, 表头排序退化为
  // antd 对当前页的客户端排序, 不冒充服务端排序。
  const serverTable = useServerTable<PortalGrantRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    serializeSort: () => ({}),
  });
  const { page, page_size: pageSize } = serverTable.params;
  const query = useQuery({
    queryKey: ["portal", endpoint, page, pageSize],
    queryFn: async () =>
      parsePortalGrantList(await apiRequest<unknown>(`${endpoint}?page=${page}&page_size=${pageSize}`)),
  });
  const grants = query.data?.data ?? [];
  serverTable.setTotal(query.data?.pagination.total_items);
  useClampPage(query.data, serverTable.query.page, serverTable.setPage);
  const columns = useMemo<ColumnsType<PortalGrantRow>>(
    () => [
      {
        key: "app",
        title: t("common.app"),
        width: 200,
        sorter: (left, right) => (left.app_name ?? "").localeCompare(right.app_name ?? ""),
        render: (_value: unknown, row: PortalGrantRow) => (
          <div className="flex min-w-0 flex-col gap-1">
            <strong className="truncate">{row.app_name ?? row.app_key ?? "-"}</strong>
            <code className={MONO_TEXT_CLASS}>{row.app_key ?? "-"}</code>
          </div>
        ),
      },
      textColumn<PortalGrantRow>({
        key: "groups",
        title: t("portal.column.groups"),
        getValue: (row) => formatGroups(row.groups),
        ellipsis: false,
      }),
      textColumn<PortalGrantRow>({
        key: "expanded_grants",
        title: t("portal.column.expandedGrants"),
        getValue: (row) => formatExpandedGrants(row.grants),
        ellipsis: false,
        mono: true,
      }),
      textColumn<PortalGrantRow>({
        key: "grant_sources",
        title: t("common.source"),
        getValue: (row) => formatSources(row.grants),
        ellipsis: false,
        mono: true,
      }),
      textColumn<PortalGrantRow>({
        key: "term",
        title: t("portal.column.term"),
        getValue: (row) => grantTypeLabel(t, row.grant_type),
        width: 110,
      }),
      textColumn<PortalGrantRow>({
        key: "versions",
        title: t("portal.column.versions"),
        getValue: (row) => formatVersions(t, row),
        ellipsis: false,
        mono: true,
        width: 220,
      }),
      dateTimeColumn<PortalGrantRow>({ key: "grant_expires_at", title: t("portal.column.expiresAt") }),
    ],
    [t],
  );

  return (
    <>
      {query.error && grants.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("portal.grants.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {query.error && grants.length === 0 ? (
        <PageState tone="signal" title={t("portal.grants.loadFailed")} description={(query.error as Error).message} />
      ) : (
        <AppTable<PortalGrantRow>
          {...serverTable.tableProps}
          columns={columns}
          dataSource={grants}
          emptyDescription={t("portal.grants.emptyDescription")}
          emptyTitle={emptyText}
          loading={query.isLoading}
          rowKey="grant_id"
        />
      )}
    </>
  );
}

function PortalRequestSection() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const serverTable = useServerTable<PortalRequestRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    serializeSort: () => ({}),
  });
  const { page, page_size: pageSize } = serverTable.params;
  const query = useQuery({
    queryKey: ["portal", "requests", page, pageSize],
    queryFn: async () =>
      parsePortalRequestList(
        await apiRequest<unknown>(`/portal/api/v1/me/access-requests?page=${page}&page_size=${pageSize}`),
      ),
  });
  const withdrawMutation = useMutation({
    mutationFn: (requestId: number) =>
      apiRequest(`/portal/api/v1/me/access-requests/${requestId}/withdraw`, {
        method: "POST",
        body: {},
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "requests"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "approvals"] });
    },
  });
  const requests = query.data?.data ?? [];
  serverTable.setTotal(query.data?.pagination.total_items);
  useClampPage(query.data, serverTable.query.page, serverTable.setPage);
  const columns = useMemo<ColumnsType<PortalRequestRow>>(
    () => [
      {
        key: "status",
        title: t("common.status"),
        width: 200,
        render: (_value: unknown, row: PortalRequestRow) => (
          <div className="flex min-w-0 flex-col gap-1">
            <span>
              <Badge tone={badgeToneForAccessRequestStatus(row.status)}>
                {row.status_label ?? accessRequestStatusLabel(t, row.status)}
              </Badge>
            </span>
            {row.decision_comment ? (
              <span className="whitespace-normal text-xs leading-4 text-ink-faint">
                {t("approvals.comment")}：{row.decision_comment}（{formatDateTime(row.decided_at)}）
              </span>
            ) : null}
          </div>
        ),
      },
      textColumn<PortalRequestRow>({
        key: "app",
        title: t("common.app"),
        getValue: (row) => row.app_name ?? row.app_key,
        sorter: true,
        width: 140,
      }),
      textColumn<PortalRequestRow>({
        key: "groups",
        title: t("portal.column.groups"),
        getValue: (row) => formatGroups(row.authorization_groups),
        ellipsis: false,
      }),
      textColumn<PortalRequestRow>({
        key: "direct_grants",
        title: t("portal.column.directGrants"),
        getValue: (row) => formatDirectGrants(row.direct_grants),
        ellipsis: false,
        mono: true,
      }),
      textColumn<PortalRequestRow>({
        key: "term",
        title: t("portal.column.term"),
        getValue: (row) => grantTypeLabel(t, row.grant_type),
        width: 110,
      }),
      dateTimeColumn<PortalRequestRow>({ key: "grant_expires_at", title: t("portal.column.expiresAt") }),
      dateTimeColumn<PortalRequestRow>({ key: "submitted_at", title: t("portal.column.submittedAt") }),
      textColumn<PortalRequestRow>({ key: "reason", title: t("portal.column.reason"), ellipsis: false }),
      actionsColumn<PortalRequestRow>({
        render: (row) => <WithdrawAction mutation={withdrawMutation} row={row} />,
      }),
    ],
    [t, withdrawMutation],
  );

  return (
    <>
      {query.error && requests.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("portal.requests.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {withdrawMutation.error ? (
        <StatusBanner live="alert" tone="signal" title={t("portal.requests.withdrawFailed")} message={(withdrawMutation.error as Error).message} />
      ) : null}
      {query.error && requests.length === 0 ? (
        <PageState tone="signal" title={t("portal.requests.loadFailed")} description={(query.error as Error).message} />
      ) : (
        <AppTable<PortalRequestRow>
          {...serverTable.tableProps}
          columns={columns}
          dataSource={requests}
          emptyDescription={t("portal.requests.emptyDescription")}
          emptyTitle={t("portal.requests.empty")}
          loading={query.isLoading}
          minWidth={1400}
          rowKey="id"
        />
      )}
    </>
  );
}

/** 只有 submitted 状态的申请可撤回, 其余行留 "-" 保持列宽稳定。 */
function WithdrawAction({
  mutation,
  row,
}: {
  mutation: ReturnType<typeof useMutation<unknown, Error, number>>;
  row: PortalRequestRow;
}) {
  const { t } = useI18n();
  const requestId = row.id;
  if (row.status !== "submitted" || typeof requestId !== "number") {
    return <>-</>;
  }
  return (
    <Button
      type="button"
      size="sm"
      variant="ghost-danger"
      loading={mutation.isPending && mutation.variables === requestId}
      disabled={mutation.isPending}
      onClick={() => mutation.mutate(requestId)}
    >
      {t("portal.requests.withdraw")}
    </Button>
  );
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

/** 服务端总页数收缩时把当前页钳制回最后一页, 否则会停在不存在的空页。 */
function useClampPage<T>(
  payload: PortalListPayload<T> | undefined,
  page: number,
  setPage: (page: number) => void,
) {
  const totalPages = payload?.pagination.total_pages;
  useEffect(() => {
    if (totalPages === undefined) {
      return;
    }
    const lastPage = Math.max(1, totalPages);
    if (page > lastPage) {
      setPage(lastPage);
    }
  }, [page, setPage, totalPages]);
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
