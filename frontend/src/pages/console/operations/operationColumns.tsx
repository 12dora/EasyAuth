import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "../../../components/Badge";
import { TableActionCell, TableRowActionButton } from "../../../components/ui/TableActions";
import { MONO_TEXT_CLASS } from "../../../components/ui/tableStyles";
import type { Translator } from "../../../lib/status";
import { accessRequestStatusLabel, badgeToneForAccessRequestStatus, formatDateTime, grantStatusLabel, healthStatusLabel } from "../../../lib/status";
import {
  auditAppKey,
  auditPair,
  booleanValue,
  healthTone,
  numberValue,
  operationAuthorizationGroupSummary,
  operationDirectGrantSummary,
  stringValue,
  type AccessRequestActionType,
  type OperationRow,
} from "./operationRow";

export interface AccessRequestColumnActions {
  disabled: boolean;
  onAction: (type: AccessRequestActionType, row: OperationRow) => void;
}

export interface AccessGrantColumnActions {
  disabled: boolean;
  onEmergencyRevoke: (row: OperationRow) => void;
}

export function operationColumns(
  section: string,
  t: Translator,
  accessRequestActions?: AccessRequestColumnActions,
  accessGrantActions?: AccessGrantColumnActions,
): ColumnDef<OperationRow>[] {
  if (section === "dependency-health") {
    return dependencyHealthColumns(t);
  }
  if (section === "audit") {
    return auditColumns(t);
  }
  if (section === "access-grants") {
    return accessGrantColumns(t, accessGrantActions);
  }
  return accessRequestColumns(t, accessRequestActions);
}

function dependencyHealthColumns(t: Translator): ColumnDef<OperationRow>[] {
  return [
    { header: t("console.operations.column.component"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.component)}</code> },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={healthTone(stringValue(row.original.status))}>{healthStatusLabel(t, stringValue(row.original.status))}</Badge> },
    { header: t("console.operations.column.summary"), cell: ({ row }) => stringValue(row.original.summary) },
    { header: t("console.operations.column.error"), cell: ({ row }) => stringValue(row.original.error_summary) },
    { header: t("console.operations.column.checkedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.last_checked_at)) },
  ];
}

function auditColumns(t: Translator): ColumnDef<OperationRow>[] {
  // 审计行字段对齐后端 audit_api._audit_item; 审计行无 id, 故不展示 ID 列。
  return [
    { header: t("console.operations.column.event"), cell: ({ row }) => stringValue(row.original.event_type) },
    { header: t("console.operations.column.actor"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditPair(row.original.actor_type, row.original.actor_id)}</code> },
    { header: t("console.operations.column.target"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditPair(row.original.target_type, row.original.target_id)}</code> },
    { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{auditAppKey(row.original)}</code> },
    { header: t("console.operations.column.time"), cell: ({ row }) => formatDateTime(stringValue(row.original.created_at)) },
  ];
}

function accessGrantColumns(
  t: Translator,
  actions: AccessGrantColumnActions | undefined,
): ColumnDef<OperationRow>[] {
  const columns: ColumnDef<OperationRow>[] = [
    { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
    { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={row.original.status === "active" ? "evergreen" : "neutral"}>{grantStatusLabel(t, stringValue(row.original.status))}</Badge> },
    {
      header: t("console.operations.column.authorizationGroups"),
      cell: ({ row }) => operationAuthorizationGroupSummary(t, row.original.authorization_groups),
    },
    {
      header: t("console.operations.column.directGrants"),
      cell: ({ row }) => operationDirectGrantSummary(t, row.original.direct_grants),
    },
    {
      header: t("console.operations.column.version"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>v{numberValue(row.original.version)}</code>,
    },
    {
      header: t("console.operations.column.isCurrent"),
      cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{booleanValue(row.original.is_current)}</code>,
    },
  ];
  if (actions) {
    columns.push({
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => renderAccessGrantActions(t, actions, row.original),
    });
  }
  return columns;
}

function renderAccessGrantActions(
  t: Translator,
  actions: AccessGrantColumnActions,
  row: OperationRow,
) {
  return (
    <TableActionCell>
      {row.status === "active" && row.is_current === true ? (
        <TableRowActionButton
          type="button"
          variant="ghost-danger"
          disabled={actions.disabled}
          onClick={() => actions.onEmergencyRevoke(row)}
        >
          {t("console.operations.emergencyRevoke")}
        </TableRowActionButton>
      ) : (
        <span className="text-caption text-ink-faint">{t("common.none")}</span>
      )}
    </TableActionCell>
  );
}

function accessRequestColumns(
  t: Translator,
  actions: AccessRequestColumnActions | undefined,
): ColumnDef<OperationRow>[] {
  const columns: ColumnDef<OperationRow>[] = [
    { header: "ID", cell: ({ row }) => row.original.id ?? "-" },
    { header: t("common.user"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.user_id)}</code> },
    { header: t("common.app"), cell: ({ row }) => <code className={MONO_TEXT_CLASS}>{stringValue(row.original.app_key)}</code> },
    { header: t("common.status"), cell: ({ row }) => <Badge tone={badgeToneForAccessRequestStatus(stringValue(row.original.status))}>{accessRequestStatusLabel(t, stringValue(row.original.status))}</Badge> },
    { header: t("common.type"), cell: ({ row }) => stringValue(row.original.request_type) },
    { header: t("console.operations.column.failureReason"), cell: ({ row }) => stringValue(row.original.failure_reason) },
    { header: t("console.operations.column.submittedAt"), cell: ({ row }) => formatDateTime(stringValue(row.original.submitted_at)) },
  ];
  if (actions) {
    columns.push({
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => renderAccessRequestActions(t, actions, row.original),
    });
  }
  return columns;
}

// 待处理申请走审批动作; 授权失败申请走显式重试, 其余状态只读。
function renderAccessRequestActions(
  t: Translator,
  actions: AccessRequestColumnActions,
  row: OperationRow,
) {
  if (row.status === "submitted") {
    return (
      <TableActionCell>
        <TableRowActionButton
          type="button"
          disabled={actions.disabled}
          onClick={() => actions.onAction("approve", row)}
        >
          {t("approvals.approve")}
        </TableRowActionButton>
        <TableRowActionButton
          type="button"
          variant="ghost-danger"
          disabled={actions.disabled}
          onClick={() => actions.onAction("reject", row)}
        >
          {t("approvals.reject")}
        </TableRowActionButton>
        <TableRowActionButton
          type="button"
          disabled={actions.disabled}
          onClick={() => actions.onAction("reassign", row)}
        >
          {t("console.accessRequests.reassign")}
        </TableRowActionButton>
      </TableActionCell>
    );
  }
  if (row.status === "grant_failed") {
    return (
      <TableActionCell>
        <TableRowActionButton
          type="button"
          disabled={actions.disabled}
          onClick={() => actions.onAction("retry-grant", row)}
        >
          {t("console.operations.retryGrant")}
        </TableRowActionButton>
      </TableActionCell>
    );
  }
  return (
    <TableActionCell>
      <span className="text-caption text-ink-faint">{t("common.none")}</span>
    </TableActionCell>
  );
}
