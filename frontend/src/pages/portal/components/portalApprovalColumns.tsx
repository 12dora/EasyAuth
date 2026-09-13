import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { Badge } from "../../../components/Badge";
import type { ColumnsType, ColumnType, ServerSortState } from "../../../components/antd/AppTable";
import {
  RowActionButton,
  actionsColumn,
  appColumn,
  dateTimeColumn,
  personColumn,
  serverSortColumn,
  textColumn,
} from "../../../components/antd/columns";
import { GrantExpiryCell } from "../../../components/grants/GrantExpiryCell";
import { formatAppDisplayName } from "../../../lib/appDisplayName";

import { badgeToneForAccessRequestStatus } from "../../../lib/status";
import type { Translator } from "../../../lib/status";

import { isFullRevokeRequest, requestTypeLabel } from "./portalApprovalFacts";
import { approvalContentSummary } from "./PortalApprovalDetails";
import type { ApprovalTab, PortalApprovalRow } from "./portalApprovalTypes";

/** 已处理表固定列宽合计; 申请内容与审批意见吃剩余宽度, 不够就横向滚动。 */
export const PROCESSED_APPROVALS_MIN_WIDTH = 1500;
/** 待办表固定列宽合计(含操作列)。 */
export const PENDING_APPROVALS_MIN_WIDTH = 1400;

/**
 * 排序发生在后端: 白名单内的数据列过 `serverSortColumn`
 * (`sorter: true` 只当开关、指示器由查询状态受控)。
 */
export function approvalColumns(
  t: Translator,
  tab: ApprovalTab,
  sort: ServerSortState,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void,
): ColumnsType<PortalApprovalRow> {
  return [
    ...identityColumns(t, sort),
    ...(tab === "processed" ? [approvalStatusColumn(t, sort)] : []),
    ...requestBodyColumns(t, sort, tab),
    ...(tab === "pending" ? [decisionActionsColumn(t, actionsDisabled, onDecision)] : decisionColumns(t, sort)),
  ];
}

function identityColumns(t: Translator, sort: ServerSortState): ColumnsType<PortalApprovalRow> {
  return [
    serverSortColumn(
      personColumn<PortalApprovalRow>({
        key: "applicant",
        title: t("portal.approvals.column.applicant"),
        t,
        getName: (approval) => approval.applicant.name,
        getUserId: (approval) => approval.applicant.user_id,
        getDepartment: (approval) => approval.applicant.department,
        getAccountKind: (approval) => approval.applicant.account_kind,
        width: 200,
      }),
      sort,
    ),
    serverSortColumn(
      appColumn<PortalApprovalRow>({
        key: "app",
        title: t("common.app"),
        width: 200,
        getDisplayName: (approval) => formatAppDisplayName({ name: approval.app_name, alias: approval.app_alias }),
        getAppKey: (approval) => approval.app_key,
      }),
      sort,
    ),
    serverSortColumn(
      {
        key: "request_type",
        title: t("portal.approvals.column.requestType"),
        width: 90,
        ellipsis: false,
        className: "whitespace-nowrap",
        render: (_value: unknown, approval: PortalApprovalRow) => requestTypeLabel(t, approval.request_type),
      },
      sort,
    ),
  ];
}

/**
 * 状态列不用 statusColumn 预设: 后端会下发本地化好的 status_label,
 * 预设只能按取值域映射, 会丢掉服务端文案。徽章色调仍走 lib/status。
 * 页签本身就是后端的 status 过滤, 列内不再放只作用于当前页的过滤。
 */
function approvalStatusColumn(t: Translator, sort: ServerSortState): ColumnType<PortalApprovalRow> {
  return serverSortColumn(
    {
      key: "status",
      title: t("common.status"),
      width: 110,
      ellipsis: false,
      className: "whitespace-nowrap",
      render: (_value: unknown, approval: PortalApprovalRow) => (
        <Badge tone={badgeToneForAccessRequestStatus(approval.status)}>{approval.status_label}</Badge>
      ),
    },
    sort,
  );
}

function requestBodyColumns(
  t: Translator,
  sort: ServerSortState,
  tab: ApprovalTab,
): ColumnsType<PortalApprovalRow> {
  return [
    serverSortColumn(
      {
        key: "content",
        title: t("portal.approvals.column.content"),
        ellipsis: false,
        render: (_value: unknown, approval: PortalApprovalRow) =>
          isFullRevokeRequest(approval) ? (
            <span className="text-ink-soft">{t("portal.approvals.fullRevoke")}</span>
          ) : (
            approvalContentSummary(approval)
          ),
      },
      sort,
    ),
    serverSortColumn(
      {
        key: "term",
        title: t("portal.column.term"),
        width: 170,
        ellipsis: false,
        render: (_value: unknown, approval: PortalApprovalRow) => (
          <GrantExpiryCell grantType={approval.grant_type} expiresAt={approval.grant_expires_at} />
        ),
      },
      sort,
    ),
    serverSortColumn(
      // 预设自带的时间戳比较函数只会重排当前页, 由 serverSortColumn 换成服务端排序。
      dateTimeColumn<PortalApprovalRow>({
        key: "submitted_at",
        title: t("portal.column.submittedAt"),
        sorter: false,
        width: 170,
      }),
      sort,
    ),
    ...(tab === "pending"
      ? [
          serverSortColumn(
            textColumn<PortalApprovalRow>({ key: "reason", title: t("portal.column.reason"), ellipsis: false }),
            sort,
          ),
        ]
      : []),
  ];
}

function decisionActionsColumn(
  t: Translator,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void,
): ColumnType<PortalApprovalRow> {
  return actionsColumn<PortalApprovalRow>({
    render: (approval) => (
      <>
        <RowActionButton type="button" disabled={actionsDisabled} onClick={() => onDecision("approve", approval)}>
          {t("approvals.approve")}
        </RowActionButton>
        <RowActionButton
          type="button"
          variant="ghost-danger"
          disabled={actionsDisabled}
          onClick={() => onDecision("reject", approval)}
        >
          {t("approvals.reject")}
        </RowActionButton>
      </>
    ),
  });
}

function decisionColumns(t: Translator, sort: ServerSortState): ColumnsType<PortalApprovalRow> {
  return [
    serverSortColumn(
      dateTimeColumn<PortalApprovalRow>({
        key: "decided_at",
        title: t("portal.approvals.column.decidedAt"),
        sorter: false,
        width: 170,
      }),
      sort,
    ),
    serverSortColumn(
      textColumn<PortalApprovalRow>({
        key: "decision_comment",
        title: t("portal.approvals.column.myComment"),
      }),
      sort,
    ),
  ];
}
