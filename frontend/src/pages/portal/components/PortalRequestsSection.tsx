import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Tooltip, theme } from "antd";
import { useMemo, useState } from "react";

import {
  AppTable,
  ORDERING_PARAM,
  orderingSerializer,
  serverTableQuery,
  useServerTable,
  type ColumnsType,
} from "../../../components/antd/AppTable";
import { RowActionButton, actionsColumn, dateTimeColumn, serverSortColumn, textColumn } from "../../../components/antd/columns";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import { accessRequestStatusColor, type AccessRequestStatusColor, type Translator } from "../../../lib/status";
import { GrantExpiryCell } from "../grantExpiry";
import { formatGrantGroupNames } from "../grantGroupNames";
import { parsePortalRequestList, type PortalRequestRow } from "../portalListPayload";
import { PORTAL_DEFAULT_PAGE_SIZE, useClampPage } from "../portalTable";
import { PortalRequestDetailDialog } from "./PortalRequestDetailDialog";

/** 申请表: 提交时间列的 key 是 payload 的 submitted_at, 后端公开的排序字段名叫 created_at。 */
const REQUEST_ORDERING_FIELDS = {
  submitted_at: "created_at",
  status: "status",
  app: "app_key",
  grant_expires_at: "expires_at",
} as const;

/**
 * 「我的申请」表格。
 *
 * 列与「我的权限」对齐(应用 / 权限组 / 期限+过期时间合并 / 操作), 逐行的细节
 * (直接授权、审批意见、流程时间点)全部收进「详情」弹窗 —— 表格里再多塞两列,
 * 桌面端就只能靠横向滚动看完一行。
 */
export function PortalRequestsSection() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [detailRow, setDetailRow] = useState<PortalRequestRow | null>(null);
  const serverTable = useServerTable<PortalRequestRow>({
    defaultPageSize: PORTAL_DEFAULT_PAGE_SIZE,
    sortParam: ORDERING_PARAM,
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
          width: 110,
          render: (_value: unknown, row: PortalRequestRow) => <RequestStatusText row={row} />,
        },
        sort,
      ),
      textColumn<PortalRequestRow>({
        key: "approver",
        title: t("portal.requests.columns.approver"),
        getValue: (row) => formatApprovers(t, row),
        width: 130,
      }),
      // 排序在后端(ordering=app_key): 预设的 localeCompare 只会重排当前页。
      serverSortColumn(
        textColumn<PortalRequestRow>({
          key: "app",
          title: t("common.app"),
          getValue: (row) => formatAppDisplayName({ name: row.app_name, alias: row.app_alias }),
          width: 140,
        }),
        sort,
      ),
      textColumn<PortalRequestRow>({
        key: "groups",
        title: t("portal.column.groups"),
        // 与「我的权限」同一个口径: 只给组名。只申请了直接授权的行这里是 "-",
        // 具体授权在详情弹窗里列。
        getValue: (row) => formatGrantGroupNames(row.authorization_groups),
        ellipsis: false,
        width: 170,
      }),
      serverSortColumn(
        {
          key: "grant_expires_at",
          title: t("portal.column.expiresAt"),
          width: 140,
          render: (_value: unknown, row: PortalRequestRow) => (
            <GrantExpiryCell grantType={row.grant_type} expiresAt={row.grant_expires_at} />
          ),
        },
        sort,
      ),
      serverSortColumn(
        dateTimeColumn<PortalRequestRow>({
          key: "submitted_at",
          title: t("portal.column.submittedAt"),
          sorter: false,
          width: 140,
        }),
        sort,
      ),
      textColumn<PortalRequestRow>({ key: "reason", title: t("portal.column.reason"), ellipsis: false, width: 180 }),
      actionsColumn<PortalRequestRow>({
        width: 130,
        render: (row) => <RequestRowActions mutation={withdrawMutation} row={row} onOpenDetail={setDetailRow} />,
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
          // 每一列都必须显式声明宽度, minWidth 必须正好等于它们的和 ——
          // AppTable 固定 `tableLayout: "fixed"`, 无宽度的列只能分摊 minWidth 的剩余量,
          // 定宽列一多剩余量就趋近 0, 权限组 / 原因会被压成一个字宽, 表头竖排成一列字。
          // 状态 110 + 审批人 130 + 应用 140 + 权限组 170 + 过期时间 140 + 提交时间 140
          // + 原因 180 + 操作 130 = 1140。
          // 加列或改列宽时这个和要一起改, `PortalRequestsSection.test.tsx` 会拦住不一致。
          minWidth={1140}
          rowKey="id"
        />
      )}
      {detailRow ? <PortalRequestDetailDialog row={detailRow} onClose={() => setDetailRow(null)} /> : null}
    </>
  );
}

/** antd 主题里承载各语义色的 token 名; 组件不写死十六进制, 换主题时跟着走。 */
const STATUS_COLOR_TOKENS: Record<AccessRequestStatusColor, "colorSuccess" | "colorInfo" | "colorError" | "colorWarning" | "colorTextTertiary"> = {
  success: "colorSuccess",
  processing: "colorInfo",
  error: "colorError",
  warning: "colorWarning",
  secondary: "colorTextTertiary",
};

/**
 * 状态列: 上色的纯文字, 不用徽章。
 *
 * 一行只有一个状态, 徽章的边框和底色在这里只是噪声; 文案直接用后端的 status_label,
 * 前端不再各自翻译一份, 免得两边口径漂移。
 */
function RequestStatusText({ row }: { row: PortalRequestRow }) {
  const { token } = theme.useToken();
  return (
    <span className="whitespace-nowrap" style={{ color: token[STATUS_COLOR_TOKENS[accessRequestStatusColor(row.status)]] }}>
      {row.status_label}
    </span>
  );
}

/**
 * 行内操作: 详情 + 撤回。
 *
 * 撤回恒在。只有 submitted 能撤回, 但把按钮整个藏起来会让员工以为功能没了或页面坏了 ——
 * 置灰 + 一句为什么, 比一个时有时无的按钮诚实。
 */
function RequestRowActions({
  mutation,
  row,
  onOpenDetail,
}: {
  mutation: ReturnType<typeof useMutation<unknown, Error, number>>;
  row: PortalRequestRow;
  onOpenDetail: (row: PortalRequestRow) => void;
}) {
  const { t } = useI18n();
  const withdrawable = row.status === "submitted";
  return (
    <>
      <RowActionButton type="button" onClick={() => onOpenDetail(row)}>
        {t("portal.requests.detail")}
      </RowActionButton>
      {/* 禁用的按钮自己收不到指针事件, 提示挂在外层 span 上才悬停得出来。 */}
      <Tooltip title={withdrawable ? "" : t("portal.requests.withdrawOnlySubmitted")}>
        <span>
          <RowActionButton
            type="button"
            variant="ghost-danger"
            loading={mutation.isPending && mutation.variables === row.id}
            disabled={!withdrawable || mutation.isPending}
            onClick={() => mutation.mutate(row.id)}
          >
            {t("portal.requests.withdraw")}
          </RowActionButton>
        </span>
      </Tooltip>
    </>
  );
}

/**
 * 审批人列: 待审批的申请给出当前审批人, 已决的申请给出决定人。
 *
 * 决定人姓名由后端解析 UserMirror 得到, 解析不出时是 null —— 这时退回展示 actor id,
 * 申请人至少还能看到是谁处理的; 已撤回 / 未决且无审批人的行由 textColumn 统一渲染 "-"。
 */
function formatApprovers(t: Translator, row: PortalRequestRow): string {
  if (row.status === "submitted") {
    return row.current_approvers.map((approver) => approver.name).join(t("portal.requests.approverSeparator"));
  }
  return row.decided_by_name ?? row.decided_by;
}
