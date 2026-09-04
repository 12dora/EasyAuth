import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { Badge } from "../../../components/Badge";
import type { ColumnsType, ColumnType, ServerSortState } from "../../../components/antd/AppTable";
import {
  MONO_TEXT_CLASS,
  RowActionButton,
  actionsColumn,
  dateTimeColumn,
  serverSortColumn,
  textColumn,
} from "../../../components/antd/columns";
import { formatAppDisplayName } from "../../../lib/appDisplayName";

import {
  accessRequestStatusLabel,
  badgeToneForAccessRequestStatus,
  formatDateTime,
  grantTypeLabel,
} from "../../../lib/status";
import type { Translator } from "../../../lib/status";

import { approvalContentDetails } from "./PortalApprovalDetails";
import { applicantLabel } from "./portalApprovalFacts";
import type { ApprovalTab, PortalApprovalRow } from "./portalApprovalTypes";

/**
 * 排序发生在后端(`ordering=applicant|app_key|created_at|decided_at`), 因此这四列过
 * `serverSortColumn`: `sorter: true` 只当开关、指示器由查询状态受控。
 * 状态 / 内容 / 期限 / 我的意见后端排不了, 不给 sorter ——
 * 客户端比较函数只会重排当前页, 与「共 N 条」自相矛盾。
 */
export function approvalColumns(
  t: Translator,
  tab: ApprovalTab,
  sort: ServerSortState,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void,
): ColumnsType<PortalApprovalRow> {
  return [
    ...(tab === "processed" ? [approvalStatusColumn(t)] : []),
    ...requestColumns(t, sort),
    ...(tab === "pending" ? [decisionActionsColumn(t, actionsDisabled, onDecision)] : decisionColumns(t, sort)),
  ];
}

/**
 * 状态列不用 statusColumn 预设: 后端会下发本地化好的 status_label,
 * 预设只能按取值域映射, 会丢掉服务端文案。徽章色调仍走 lib/status。
 * 页签本身就是后端的 status 过滤, 列内不再放只作用于当前页的过滤。
 */
function approvalStatusColumn(t: Translator): ColumnType<PortalApprovalRow> {
  return {
    key: "status",
    title: t("common.status"),
    width: 130,
    render: (_value: unknown, approval: PortalApprovalRow) => (
      <Badge tone={badgeToneForAccessRequestStatus(approval.status)}>
        {approval.status_label ?? accessRequestStatusLabel(t, approval.status)}
      </Badge>
    ),
  };
}

function requestColumns(t: Translator, sort: ServerSortState): ColumnsType<PortalApprovalRow> {
  return [
    serverSortColumn(
      {
        key: "applicant",
        title: t("portal.approvals.column.applicant"),
        width: 160,
        render: (_value: unknown, approval: PortalApprovalRow) => (
          <div className="flex min-w-0 flex-col gap-1">
            <strong className="truncate">{applicantLabel(approval)}</strong>
            {approval.applicant?.department ? (
              <span className="text-xs leading-4 text-ink-faint">{approval.applicant.department}</span>
            ) : null}
          </div>
        ),
      },
      sort,
    ),
    serverSortColumn(
      {
        key: "app",
        title: t("common.app"),
        width: 160,
        render: (_value: unknown, approval: PortalApprovalRow) => (
          <div className="flex min-w-0 flex-col gap-1">
            <strong className="truncate">
              {formatAppDisplayName({ name: approval.app_name, alias: approval.app_alias })}
            </strong>
            <code className={MONO_TEXT_CLASS}>{approval.app_key}</code>
          </div>
        ),
      },
      sort,
    ),
    {
      key: "content",
      title: t("portal.approvals.column.content"),
      render: (_value: unknown, approval: PortalApprovalRow) => approvalContentDetails(t, approval),
    },
    {
      key: "term",
      title: t("portal.column.term"),
      width: 130,
      render: (_value: unknown, approval: PortalApprovalRow) => (
        <div className="flex min-w-0 flex-col gap-1">
          <span>{grantTypeLabel(t, approval.grant_type)}</span>
          {approval.grant_expires_at ? (
            <span className="text-xs leading-4 text-ink-faint">{formatDateTime(approval.grant_expires_at)}</span>
          ) : null}
        </div>
      ),
    },
    serverSortColumn(
      // 预设自带的时间戳比较函数只会重排当前页, 由 serverSortColumn 换成服务端排序。
      dateTimeColumn<PortalApprovalRow>({
        key: "submitted_at",
        title: t("portal.column.submittedAt"),
        sorter: false,
      }),
      sort,
    ),
    textColumn<PortalApprovalRow>({ key: "reason", title: t("portal.column.reason"), ellipsis: false }),
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
      }),
      sort,
    ),
    textColumn<PortalApprovalRow>({
      key: "decision_comment",
      title: t("portal.approvals.column.myComment"),
      ellipsis: false,
    }),
  ];
}
