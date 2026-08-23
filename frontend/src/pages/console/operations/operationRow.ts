import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import type { OperationRow as DomainOperationRow } from "../../../lib/domain";
import type { OperationAuthorizationGroup, OperationDirectGrant } from "../../../lib/domain";
import type { Translator } from "../../../lib/status";
import { formatDateTime, grantTypeLabel } from "../../../lib/status";

export type OperationRow = DomainOperationRow & {
  version?: number;
  is_current?: boolean;
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

export function requiredString(value: unknown): string {
  if (typeof value !== "string" || value === "") {
    throw new Error("Operation row is missing a required string field.");
  }
  return value;
}

export function numberValue(value: unknown): string {
  return typeof value === "number" && Number.isInteger(value) ? String(value) : "-";
}

export function booleanValue(value: unknown): string {
  return typeof value === "boolean" ? String(value) : "-";
}

export function operationAuthorizationGroupSummary(
  t: Translator,
  value: OperationAuthorizationGroup[] | undefined,
): string {
  if (!Array.isArray(value)) {
    throw new Error(t("console.operations.contract.authorizationGroups"));
  }
  if (value.length === 0) {
    return t("common.none");
  }
  return value.map((group, index) => {
    const key = requiredContractString(t, group.key, `authorization_groups[${index}].key`);
    const name = requiredContractString(t, group.name, `authorization_groups[${index}].name`);
    return `${name || key} (${operationItemTerm(t, group.expires_at, `authorization_groups[${index}].expires_at`)})`;
  }).join("；");
}

export function operationDirectGrantSummary(
  t: Translator,
  value: OperationDirectGrant[] | undefined,
): string {
  if (!Array.isArray(value)) {
    throw new Error(t("console.operations.contract.directGrants"));
  }
  if (value.length === 0) {
    return t("common.none");
  }
  return value.map((grant, index) => {
    const permission = requiredContractString(t, grant.permission, `direct_grants[${index}].permission`);
    const name = requiredContractString(t, grant.permission_name, `direct_grants[${index}].permission_name`);
    const scope = requiredContractString(t, grant.scope, `direct_grants[${index}].scope`);
    const term = operationItemTerm(t, grant.expires_at, `direct_grants[${index}].expires_at`);
    return `${name || permission} [${scope}] (${term})`;
  }).join("；");
}

function operationItemTerm(t: Translator, value: unknown, field: string): string {
  if (value === null) {
    return grantTypeLabel(t, "permanent");
  }
  return formatDateTime(requiredContractString(t, value, field));
}

function requiredContractString(t: Translator, value: unknown, field: string): string {
  if (typeof value !== "string" || value === "") {
    throw new Error(t("console.operations.contract.requiredString", { field }));
  }
  return value;
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
