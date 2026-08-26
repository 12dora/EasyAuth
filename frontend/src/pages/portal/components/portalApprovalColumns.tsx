import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import type { ColumnsType, ColumnType } from "../../../components/antd/AppTable";
import { MONO_TEXT_CLASS, actionsColumn, dateTimeColumn, textColumn } from "../../../components/antd/columns";

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

export function approvalColumns(
  t: Translator,
  tab: ApprovalTab,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void,
): ColumnsType<PortalApprovalRow> {
  return [
    ...(tab === "processed" ? [approvalStatusColumn(t)] : []),
    ...requestColumns(t),
    ...(tab === "pending" ? [decisionActionsColumn(t, actionsDisabled, onDecision)] : decisionColumns(t)),
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

function requestColumns(t: Translator): ColumnsType<PortalApprovalRow> {
  return [
    {
      key: "applicant",
      title: t("portal.approvals.column.applicant"),
      width: 160,
      sorter: (left, right) => applicantLabel(left).localeCompare(applicantLabel(right)),
      render: (_value: unknown, approval: PortalApprovalRow) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong className="truncate">{applicantLabel(approval)}</strong>
          {approval.applicant?.department ? (
            <span className="text-xs leading-4 text-ink-faint">{approval.applicant.department}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "app",
      title: t("common.app"),
      width: 160,
      sorter: (left, right) => (left.app_name ?? "").localeCompare(right.app_name ?? ""),
      render: (_value: unknown, approval: PortalApprovalRow) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong className="truncate">{approval.app_name ?? approval.app_key ?? "-"}</strong>
          <code className={MONO_TEXT_CLASS}>{approval.app_key ?? "-"}</code>
        </div>
      ),
    },
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
    dateTimeColumn<PortalApprovalRow>({ key: "submitted_at", title: t("portal.column.submittedAt") }),
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
        <Button type="button" size="sm" variant="ghost" disabled={actionsDisabled} onClick={() => onDecision("approve", approval)}>
          {t("approvals.approve")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost-danger"
          disabled={actionsDisabled}
          onClick={() => onDecision("reject", approval)}
        >
          {t("approvals.reject")}
        </Button>
      </>
    ),
  });
}

function decisionColumns(t: Translator): ColumnsType<PortalApprovalRow> {
  return [
    dateTimeColumn<PortalApprovalRow>({
      key: "decided_at",
      title: t("portal.approvals.column.decidedAt"),
    }),
    textColumn<PortalApprovalRow>({
      key: "decision_comment",
      title: t("portal.approvals.column.myComment"),
      ellipsis: false,
    }),
  ];
}
