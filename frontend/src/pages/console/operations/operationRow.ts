import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import type { OperationRow as DomainOperationRow } from "../../../lib/domain";
import { formatAppDisplayName } from "../../../lib/appDisplayName";

export type OperationRow = DomainOperationRow & {
  failure_reason?: string;
};

export type AccessRequestActionType = ApprovalDecisionMode | "reassign" | "retry-grant";

export interface AccessRequestAction {
  type: AccessRequestActionType;
  row: OperationRow;
}

export interface OperationNotice {
  tone: "amber" | "signal";
  title: string;
  message?: string;
}

export function stringValue(value: unknown): string {
  return typeof value === "string" && value !== "" ? value : "-";
}

/**
 * 申请行的应用展示名(`别名 (技术名)`)。
 *
 * `app_name` 由后端契约保证存在, 缺失即契约违约, 直接抛错而不是退回展示 app_key;
 * `app_alias` 允许为空串(应用没配别名), 此时只展示技术名。
 */
export function operationAppDisplayName(row: OperationRow): string {
  if (typeof row.app_name !== "string" || row.app_name === "") {
    throw new Error("Operation row is missing app_name.");
  }
  return formatAppDisplayName({ name: row.app_name, alias: row.app_alias });
}

/** 审批人列: 只展示姓名, 目录里没有姓名的审批人回落展示其 user_id。 */
export function operationApproverNames(row: OperationRow): string {
  const approvers = row.approvers ?? [];
  if (approvers.length === 0) {
    return "-";
  }
  return approvers.map((approver) => approver.name || approver.user_id).join("、");
}

export function auditPair(type: string | undefined, id: string | undefined): string {
  const parts = [type, id].filter((part): part is string => typeof part === "string" && part !== "");
  return parts.length > 0 ? parts.join(":") : "-";
}

export function auditAppKey(row: OperationRow): string {
  // 非超管审计以 metadata.app_key 做作用域, app_key 不在顶层字段而在 metadata 中。
  const appKey = row.metadata && typeof row.metadata === "object" ? row.metadata.app_key : undefined;
  return typeof appKey === "string" && appKey !== "" ? appKey : "-";
}

export function healthTone(status: string): "evergreen" | "amber" | "neutral" | "signal" {
  if (status === "healthy") {
    return "evergreen";
  }
  if (status === "warning") {
    return "amber";
  }
  if (status === "unknown") {
    return "neutral";
  }
  return "signal";
}
