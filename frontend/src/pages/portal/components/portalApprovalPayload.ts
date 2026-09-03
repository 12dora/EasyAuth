import { ApiError } from "../../../lib/api";
import type { Pagination } from "../../../lib/api";
import type { PortalApprovalApplicant, PortalRequestApprover } from "../../../lib/domain";

import type {
  ApprovalAuthorizationGroup,
  ApprovalGrantFact,
  ApprovalListPayload,
  CommittedGrantStatus,
  PortalApprovalRow,
} from "./portalApprovalTypes";

const APPROVAL_REQUEST_TYPES = new Set(["grant", "change", "revoke", "renew"]);
const APPROVAL_STATUSES = new Set([
  "submitted",
  "approved",
  "rejected",
  "grant_applied",
  "grant_failed",
  "grant_conflict",
  "grant_expired",
  // 申请人可在审批人打开详情之前撤回: 审批分配还在, 详情接口照样返回这条 withdrawn 行。
  // 少了它详情会被判成非法载荷并重试到失败, 而不是落到「已处理」的冲突提示。
  "withdrawn",
]);
const APPROVAL_GRANT_TYPES = new Set(["permanent", "timed"]);
// 未决时后端给空字符串, 决定后给 user / console_admin; 空串是合法取值而非缺失。
const APPROVAL_DECISION_ACTOR_TYPES = new Set(["", "user", "console_admin"]);
const APPROVAL_ROW_KEYS = [
  "id",
  "app_key",
  "app_name",
  "request_type",
  "base_grant_id",
  "base_grant_revision",
  "status",
  "status_label",
  "grant_type",
  "grant_expires_at",
  "reason",
  "submitted_at",
  "authorization_groups",
  "direct_grants",
  "current_approvers",
  "decided_at",
  "decision_comment",
  "applicant",
  "approver_user_ids",
  "decided_by",
  "decision_actor_type",
  "decided_by_name",
] as const;

export function committedGrantStatus(error: unknown, expectedApprovalId: number): CommittedGrantStatus | null {
  if (!(error instanceof ApiError) || error.status !== 422 || !isRecord(error.details)) {
    return null;
  }
  const status = error.details.status;
  if (status !== "grant_failed" && status !== "grant_expired") {
    return null;
  }
  const approval = error.details.approval;
  return (
    error.details.decision_committed === true &&
    isPortalApprovalRow(approval) &&
    approval.id === expectedApprovalId &&
    approval.status === status
  )
    ? status
    : null;
}

export function applicationConflictRequiresResubmit(error: ApiError): boolean {
  if (!isRecord(error.details)) {
    return false;
  }
  return (
    error.details.reason === "base_grant_revision_conflict" ||
    error.details.reason === "request_expired"
  );
}

export function parseApprovalListPayload(payload: unknown, errorMessage: string): ApprovalListPayload {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["data", "pagination"]) ||
    !Array.isArray(payload.data) ||
    !isPagination(payload.pagination)
  ) {
    throw new Error(errorMessage);
  }
  const expectedTotalPages = Math.ceil(payload.pagination.total_items / payload.pagination.page_size);
  if (
    payload.pagination.total_pages !== expectedTotalPages ||
    payload.pagination.page > Math.max(payload.pagination.total_pages, 1) ||
    payload.data.length > payload.pagination.page_size ||
    !payload.data.every(isPortalApprovalRow)
  ) {
    throw new Error(errorMessage);
  }
  return { data: payload.data, pagination: payload.pagination };
}

export function parseApprovalDetailPayload(
  payload: unknown,
  errorMessage: string,
  expectedApprovalId: number,
): { approval: PortalApprovalRow } {
  if (
    !isRecord(payload) ||
    !hasExactKeys(payload, ["approval"]) ||
    !isPortalApprovalRow(payload.approval) ||
    payload.approval.id !== expectedApprovalId
  ) {
    throw new Error(errorMessage);
  }
  return { approval: payload.approval };
}

function isPortalApprovalRow(value: unknown): value is PortalApprovalRow {
  if (!isRecord(value) || !hasExactKeys(value, APPROVAL_ROW_KEYS)) {
    return false;
  }
  return (
    hasApprovalIdentity(value) &&
    hasApprovalLifecycleShape(value) &&
    hasApprovalTargets(value) &&
    hasApprovalDecisionShape(value)
  );
}

function hasApprovalIdentity(value: Record<string, unknown>): boolean {
  const requiredStrings = [
    value.app_key,
    value.app_name,
    value.request_type,
    value.status,
    value.status_label,
    value.grant_type,
    value.reason,
    value.submitted_at,
  ];
  return (
    Number.isInteger(value.id) &&
    typeof value.id === "number" &&
    value.id > 0 &&
    requiredStrings.every(isNonEmptyString)
  );
}

function hasApprovalLifecycleShape(value: Record<string, unknown>): boolean {
  return (
    APPROVAL_REQUEST_TYPES.has(value.request_type as string) &&
    isLifecycleBaseGrantShape(value.request_type as string, value.base_grant_id, value.base_grant_revision) &&
    APPROVAL_STATUSES.has(value.status as string) &&
    APPROVAL_GRANT_TYPES.has(value.grant_type as string) &&
    isNullableDateTimeString(value.grant_expires_at) &&
    (value.grant_type === "timed" ? value.grant_expires_at !== null : value.grant_expires_at === null) &&
    isDateTimeString(value.submitted_at)
  );
}

function hasApprovalTargets(value: Record<string, unknown>): boolean {
  return (
    Array.isArray(value.authorization_groups) &&
    value.authorization_groups.every(isApprovalAuthorizationGroup) &&
    Array.isArray(value.direct_grants) &&
    value.direct_grants.every(isApprovalGrantFact)
  );
}

function hasApprovalDecisionShape(value: Record<string, unknown>): boolean {
  return (
    isNullableDateTimeString(value.decided_at) &&
    isNullableString(value.decision_comment) &&
    isApprovalApplicant(value.applicant) &&
    hasApprovalActorShape(value) &&
    hasApprovalApproverShape(value)
  );
}

/**
 * 决定人三件套: actor id、actor 身份、显示名。
 * 未决时后端给 ""/""/null, 所以只能按可空字符串与枚举校验, 不能要求非空。
 */
function hasApprovalActorShape(value: Record<string, unknown>): boolean {
  return (
    isNullableString(value.decided_by) &&
    isApprovalDecisionActorType(value.decision_actor_type) &&
    isNullableString(value.decided_by_name)
  );
}

/**
 * approver_user_ids 是这条申请的全部审批人候选,
 * current_approvers 是当前待处理的分配(仅 submitted 非空), 两者都必须逐项校验,
 * 否则列表页会拿着不可信的审批人事实渲染。
 */
function hasApprovalApproverShape(value: Record<string, unknown>): boolean {
  return (
    Array.isArray(value.approver_user_ids) &&
    value.approver_user_ids.every((item) => typeof item === "string") &&
    Array.isArray(value.current_approvers) &&
    value.current_approvers.every(isApprovalApprover)
  );
}

function isApprovalDecisionActorType(value: unknown): value is string {
  return typeof value === "string" && APPROVAL_DECISION_ACTOR_TYPES.has(value);
}

function isApprovalApprover(value: unknown): value is PortalRequestApprover {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["user_id", "name"]) &&
    isNonEmptyString(value.user_id) &&
    typeof value.name === "string"
  );
}

function isLifecycleBaseGrantShape(
  requestType: string,
  baseGrantId: unknown,
  baseGrantRevision: unknown,
): boolean {
  if (requestType === "grant") {
    return baseGrantId === null && baseGrantRevision === null;
  }
  return isIntegerAtLeast(baseGrantId, 1) && isIntegerAtLeast(baseGrantRevision, 1);
}

function isApprovalAuthorizationGroup(value: unknown): value is ApprovalAuthorizationGroup {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["key", "kind", "name", "grants"]) &&
    isNonEmptyString(value.key) &&
    (value.kind === "role" || value.kind === "bundle") &&
    typeof value.name === "string" &&
    Array.isArray(value.grants) &&
    value.grants.every(isApprovalGrantFact)
  );
}

function isApprovalGrantFact(value: unknown): value is ApprovalGrantFact {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["permission", "permission_name", "scope"]) &&
    isNonEmptyString(value.permission) &&
    typeof value.permission_name === "string" &&
    isNonEmptyString(value.scope)
  );
}

function isApprovalApplicant(value: unknown): value is Required<PortalApprovalApplicant> {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["user_id", "name", "email", "department"]) &&
    isNonEmptyString(value.user_id) &&
    typeof value.name === "string" &&
    typeof value.email === "string" &&
    typeof value.department === "string"
  );
}

function isPagination(value: unknown): value is Pagination {
  return (
    isRecord(value) &&
    hasExactKeys(value, ["page", "page_size", "total_items", "total_pages"]) &&
    isIntegerAtLeast(value.page, 1) &&
    isIntegerAtLeast(value.page_size, 1) &&
    isIntegerAtLeast(value.total_items, 0) &&
    isIntegerAtLeast(value.total_pages, 0)
  );
}

function isIntegerAtLeast(value: unknown, minimum: number): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= minimum;
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isDateTimeString(value: unknown): value is string {
  return typeof value === "string" && value.includes("T") && !Number.isNaN(Date.parse(value));
}

function isNullableDateTimeString(value: unknown): value is string | null {
  return value === null || isDateTimeString(value);
}

function hasExactKeys(value: Record<string, unknown>, expectedKeys: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expectedKeys.length && expectedKeys.every((key) => key in value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
