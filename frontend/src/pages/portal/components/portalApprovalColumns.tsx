import type { ColumnDef } from "@tanstack/react-table";

import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { Badge } from "../../../components/Badge";
import { TableActionCell, TableRowActionButton } from "../../../components/ui/TableActions";
import { MONO_TEXT_CLASS } from "../../../components/ui/tableStyles";
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
): ColumnDef<PortalApprovalRow>[] {
  return [
    ...(tab === "processed" ? [statusColumn(t)] : []),
    ...requestColumns(t),
    ...(tab === "pending" ? [actionsColumn(t, actionsDisabled, onDecision)] : decisionColumns(t)),
  ];
}

function statusColumn(t: Translator): ColumnDef<PortalApprovalRow> {
  return {
    header: t("common.status"),
    cell: ({ row }) => (
      <Badge tone={badgeToneForAccessRequestStatus(row.original.status)}>
        {row.original.status_label ?? accessRequestStatusLabel(t, row.original.status)}
      </Badge>
    ),
  };
}

function requestColumns(t: Translator): ColumnDef<PortalApprovalRow>[] {
  return [
    {
      header: t("portal.approvals.column.applicant"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{applicantLabel(row.original)}</strong>
          {row.original.applicant?.department ? (
            <span className="text-xs leading-4 text-ink-faint">{row.original.applicant.department}</span>
          ) : null}
        </div>
      ),
    },
    {
      header: t("common.app"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <strong>{row.original.app_name ?? row.original.app_key ?? "-"}</strong>
          <code className={MONO_TEXT_CLASS}>{row.original.app_key ?? "-"}</code>
        </div>
      ),
    },
    { header: t("portal.approvals.column.content"), cell: ({ row }) => approvalContentDetails(t, row.original) },
    {
      header: t("portal.column.term"),
      cell: ({ row }) => (
        <div className="flex min-w-0 flex-col gap-1">
          <span>{grantTypeLabel(t, row.original.grant_type)}</span>
          {row.original.grant_expires_at ? (
            <span className="text-xs leading-4 text-ink-faint">{formatDateTime(row.original.grant_expires_at)}</span>
          ) : null}
        </div>
      ),
    },
    { header: t("portal.column.submittedAt"), cell: ({ row }) => formatDateTime(row.original.submitted_at) },
    { header: t("portal.column.reason"), cell: ({ row }) => row.original.reason ?? "-" },
  ];
}

function actionsColumn(
  t: Translator,
  actionsDisabled: boolean,
  onDecision: (mode: ApprovalDecisionMode, approval: PortalApprovalRow) => void,
): ColumnDef<PortalApprovalRow> {
  return {
    id: "actions",
    header: t("common.actions"),
    cell: ({ row }) => (
      <TableActionCell>
        <TableRowActionButton type="button" disabled={actionsDisabled} onClick={() => onDecision("approve", row.original)}>
          {t("approvals.approve")}
        </TableRowActionButton>
        <TableRowActionButton
          type="button"
          variant="ghost-danger"
          disabled={actionsDisabled}
          onClick={() => onDecision("reject", row.original)}
        >
          {t("approvals.reject")}
        </TableRowActionButton>
      </TableActionCell>
    ),
  };
}

function decisionColumns(t: Translator): ColumnDef<PortalApprovalRow>[] {
  return [
    { header: t("portal.approvals.column.decidedAt"), cell: ({ row }) => formatDateTime(row.original.decided_at) },
    { header: t("portal.approvals.column.myComment"), cell: ({ row }) => row.original.decision_comment || "-" },
  ];
}
