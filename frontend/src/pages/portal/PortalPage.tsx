import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useOutletContext } from "react-router-dom";

import type { AppShellOutletContext } from "../../components/AppShell";
import {
  AppTable,
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
  type ColumnsType,
} from "../../components/antd/AppTable";
import {
  MONO_TEXT_CLASS,
  RowActionButton,
  actionsColumn,
  dateTimeColumn,
  serverSortColumn,
  textColumn,
} from "../../components/antd/columns";
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

/**
 * 授权表的列 key -> 后端 `ordering` 字段。
 *
 * 接口另外允许 `created_at`, 但表里没有「授权时间」这一列 —— 给一个看不见的字段
 * 排序只会让人猜不到表格为什么变了顺序, 因此只映射展示得出来的两列。
 * 应用列同时显示名字与 app_key, 排序按后端默认序的那一个(app_key)。
 */
const GRANT_ORDERING_FIELDS = { app: "app_key", grant_expires_at: "expires_at" } as const;
/** 后端默认序是 app_key 升序; defaultSort 与它一致, 首屏表头就带排序指示器。 */
const GRANT_DEFAULT_SORT = { field: "app", order: "ascend" } as const;

/** 申请表: 提交时间列的 key 是 payload 的 submitted_at, 后端公开的排序字段名叫 created_at。 */
const REQUEST_ORDERING_FIELDS = {
  submitted_at: "created_at",
  status: "status",
  app: "app_key",
  grant_expires_at: "expires_at",
} as const;
/** 后端默认序是 -created_at(即按提交时间倒序)。 */
const REQUEST_DEFAULT_SORT = { field: "submitted_at", order: "descend" } as const;

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
      {view === "grants" ? (
        <PortalGrantSection
          ariaLabel={t("portal.grants.ariaLabel")}
          endpoint="/portal/api/v1/me/grants"
          emptyText={t("portal.grants.emptyCurrent")}
        />
      ) : null}
      {view === "expiring" ? (
        <PortalGrantSection
          ariaLabel={t("portal.grants.expiringAriaLabel")}
          endpoint="/portal/api/v1/me/grants/expiring"
          emptyText={t("portal.grants.emptyExpiring")}
        />
      ) : null}
      {view === "requests" ? <PortalRequestSection /> : null}
      {view === "request" ? <AccessRequestForm currentUserId={currentUserId} /> : null}
      {view === "approvals" ? <PortalApprovalsSection /> : null}
      {preOffboardOpen ? <PortalPreOffboardDialog onClose={() => setPreOffboardOpen(false)} /> : null}
    </>
  );
}

function PortalGrantSection({
  ariaLabel,
  endpoint,
  emptyText,
}: {
  /** 表格的无障碍名字; 当前授权与即将过期是两张不同的表, 名字也不同。 */
  ariaLabel: string;
  endpoint: string;
  emptyText: string;
}) {
  const { t } = useI18n();
  const serverTable = useServerTable<PortalGrantRow>({
    defaultPageSize: DEFAULT_PAGE_SIZE,
    sortParam: ORDERING_PARAM,
    defaultSort: GRANT_DEFAULT_SORT,
    serializeSort: orderingSerializer(GRANT_ORDERING_FIELDS),
  });
  const sort = serverTable.query;
  // ordering 必须一起进查询串和查询键, 否则点了表头也不会重新请求。
  const grantsSearch = serverTableQuery(serverTable.params);
  const query = useQuery({
    queryKey: ["portal", endpoint, grantsSearch],
    queryFn: async () => parsePortalGrantList(await apiRequest<unknown>(`${endpoint}?${grantsSearch}`)),
  });
  const grants = query.data?.data ?? [];
  serverTable.setTotal(query.data?.pagination.total_items);
  useClampPage(query.data, serverTable.query.page, serverTable.setPage);
  const columns = useMemo<ColumnsType<PortalGrantRow>>(
    () => [
      // 排序在后端(ordering=app_key): 原来挂在这列上的 localeCompare 只会重排当前页,
      // 表头写着按应用排序, 实际只是把这 20 行内部换了个顺序。
      serverSortColumn(
        {
          key: "app",
          title: t("common.app"),
          width: 200,
          render: (_value: unknown, row: PortalGrantRow) => (
            <div className="flex min-w-0 flex-col gap-1">
              <strong className="truncate">{row.app_name ?? row.app_key ?? "-"}</strong>
              <code className={MONO_TEXT_CLASS}>{row.app_key ?? "-"}</code>
            </div>
          ),
        },
        sort,
      ),
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
      serverSortColumn(
        // 预设自带的时间戳比较函数只会重排当前页, 由 serverSortColumn 换成服务端排序。
        dateTimeColumn<PortalGrantRow>({ key: "grant_expires_at", title: t("portal.column.expiresAt"), sorter: false }),
        sort,
      ),
    ],
    [sort, t],
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
          ariaLabel={ariaLabel}
          columns={columns}
          dataSource={grants}
          emptyDescription={t("portal.grants.emptyDescription")}
          emptyTitle={emptyText}
          loading={query.isLoading}
          // 固定列 200(应用) + 110(期限) + 220(版本) + 170(过期时间) = 700,
          // 权限组 / 展开授权 / 来源三列不定宽(ellipsis: false, 长文本换行)各留 180 -> 1240。
          minWidth={1240}
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
    sortParam: ORDERING_PARAM,
    defaultSort: REQUEST_DEFAULT_SORT,
    serializeSort: orderingSerializer(REQUEST_ORDERING_FIELDS),
  });
  const sort = serverTable.query;
  // ordering 必须一起进查询串和查询键, 否则点了表头也不会重新请求。
  const requestsSearch = serverTableQuery(serverTable.params);
  const query = useQuery({
    queryKey: ["portal", "requests", requestsSearch],
    queryFn: async () =>
      parsePortalRequestList(await apiRequest<unknown>(`/portal/api/v1/me/access-requests?${requestsSearch}`)),
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
      serverSortColumn(
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
        sort,
      ),
      // 排序在后端(ordering=app_key): 预设的 localeCompare 只会重排当前页。
      serverSortColumn(
        textColumn<PortalRequestRow>({
          key: "app",
          title: t("common.app"),
          getValue: (row) => row.app_name ?? row.app_key,
          width: 140,
        }),
        sort,
      ),
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
      serverSortColumn(
        dateTimeColumn<PortalRequestRow>({ key: "grant_expires_at", title: t("portal.column.expiresAt"), sorter: false }),
        sort,
      ),
      serverSortColumn(
        dateTimeColumn<PortalRequestRow>({ key: "submitted_at", title: t("portal.column.submittedAt"), sorter: false }),
        sort,
      ),
      textColumn<PortalRequestRow>({ key: "reason", title: t("portal.column.reason"), ellipsis: false }),
      actionsColumn<PortalRequestRow>({
        render: (row) => <WithdrawAction mutation={withdrawMutation} row={row} />,
      }),
    ],
    [sort, t, withdrawMutation],
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
          ariaLabel={t("portal.requests.ariaLabel")}
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
    <RowActionButton
      type="button"
      variant="ghost-danger"
      loading={mutation.isPending && mutation.variables === requestId}
      disabled={mutation.isPending}
      onClick={() => mutation.mutate(requestId)}
    >
      {t("portal.requests.withdraw")}
    </RowActionButton>
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
