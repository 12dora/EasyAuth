import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useOutletContext } from "react-router-dom";

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
  serverSortColumn,
  textColumn,
} from "../../components/antd/columns";
import { PageState } from "../../components/ui/PageState";

import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest } from "../../lib/api";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import type { Translator } from "../../lib/status";
import { useI18n } from "../../i18n/I18nProvider";
import { AccessRequestForm } from "./components/AccessRequestForm";
import { GrantPermissionsCell } from "./components/GrantPermissionsCell";
import { PortalApprovalsSection } from "./components/PortalApprovalsSection";
import { PortalRequestsSection } from "./components/PortalRequestsSection";
import { PortalPreOffboardDialog } from "./PortalPreOffboardDialog";
import { GrantExpiryCell } from "./grantExpiry";
import { formatGrantGroupNames } from "./grantGroupNames";
import { parsePortalGrantList, type PortalGrantRow } from "./portalListPayload";
import { PORTAL_DEFAULT_PAGE_SIZE, useClampPage } from "./portalTable";

export type PortalView = "grants" | "request" | "requests" | "expiring" | "approvals";

/**
 * 授权表的列 key -> 后端 `ordering` 字段。
 *
 * 接口另外允许 `created_at`, 但表里没有「授权时间」这一列 —— 给一个看不见的字段
 * 排序只会让人猜不到表格为什么变了顺序, 因此只映射展示得出来的两列。
 * 应用列同时显示名字与 app_key, 排序按后端默认序的那一个(app_key)。
 */
const GRANT_ORDERING_FIELDS = { app: "app_key", grant_expires_at: "expires_at" } as const;

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
      {view === "requests" ? <PortalRequestsSection /> : null}
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
    defaultPageSize: PORTAL_DEFAULT_PAGE_SIZE,
    sortParam: ORDERING_PARAM,
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
              <strong className="truncate">{formatAppDisplayName({ name: row.app_name, alias: row.app_alias })}</strong>
              <code className={MONO_TEXT_CLASS}>{row.app_key ?? "-"}</code>
            </div>
          ),
        },
        sort,
      ),
      textColumn<PortalGrantRow>({
        key: "groups",
        title: t("portal.column.groups"),
        getValue: (row) => formatGrantGroupNames(row.groups),
        ellipsis: false,
        width: 200,
      }),
      {
        key: "permission_details",
        title: t("portal.column.permissionDetails"),
        width: 160,
        render: (_value: unknown, row: PortalGrantRow) => <GrantPermissionsCell row={row} />,
      },
      serverSortColumn(
        {
          key: "grant_expires_at",
          title: t("portal.column.expiresAt"),
          width: 220,
          render: (_value: unknown, row: PortalGrantRow) => (
            <GrantExpiryCell grantType={row.grant_type} expiresAt={row.grant_expires_at} />
          ),
        },
        sort,
      ),
      actionsColumn<PortalGrantRow>({
        width: 160,
        render: (row) => <UpdateGrantAction row={row} />,
      }),
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
          // 同「我的申请」: 每列都声明宽度, minWidth 正好等于它们的和 —— fixed 布局下
          // 无宽度的列只能分摊剩余量, 剩余量不够就会被压成一个字宽。
          // 应用 200 + 权限组 200 + 权限详情 160 + 过期时间 220 + 操作 160 = 940。
          minWidth={940}
          rowKey="grant_id"
        />
      )}
    </>
  );
}

/**
 * 「更新权限」: 带着当前授权跳到申请页, 申请类型预置为变更。
 *
 * 员工要调整已有权限时, 手动流程是「进申请页 -> 选变更 -> 在下拉里找回这条授权」;
 * 这里把这三步压成一次点击, 路由 state 里的 baseGrantId 与表单的基础授权下拉同一个口径
 * (字符串形式的 grant_id)。
 */
function UpdateGrantAction({ row }: { row: PortalGrantRow }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  return (
    <RowActionButton
      type="button"
      onClick={() =>
        navigate("/portal/request", {
          state: { accessRequestPrefill: { requestType: "change", baseGrantId: String(row.grant_id) } },
        })
      }
    >
      {t("portal.grants.updatePermissions")}
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
