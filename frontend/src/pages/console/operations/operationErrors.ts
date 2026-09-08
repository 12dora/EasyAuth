import { ApiError } from "../../../lib/api";
import type { JsonObject, JsonValue } from "../../../lib/api";

/** 已显式迁移到页面级提示的错误不在弹窗内重复展示。 */
export function dialogErrorMessage(
  error: Error | null,
  options: { hideConflict?: boolean; hideDecisionCommitted?: boolean } = {},
): string {
  if (!error) {
    return "";
  }
  if (options.hideConflict && error instanceof ApiError && error.status === 409) {
    return "";
  }
  if (options.hideDecisionCommitted && isDecisionCommittedError(error)) {
    return "";
  }
  return error.message;
}

export function isDecisionCommittedError(error: Error): boolean {
  return error instanceof ApiError && detailFlag(error.details, "decision_committed") === true;
}

export function isActiveGrantNotFoundConflict(error: Error): boolean {
  return isRevokeConflict(error, "active_grant_not_found");
}

/** 权限来自组织授权: 只能在组织授权里调整, 不是一次可重试的失败。 */
export function isDepartmentSourcedGrantConflict(error: Error): boolean {
  return isRevokeConflict(error, "department_sourced_grant");
}

function isRevokeConflict(error: Error, reason: string): boolean {
  return error instanceof ApiError && error.status === 409 && detailString(error.details, "reason") === reason;
}

function detailFlag(details: JsonValue | undefined, key: string): boolean | undefined {
  return isJsonObject(details) && typeof details[key] === "boolean" ? details[key] : undefined;
}

function detailString(details: JsonValue | undefined, key: string): string | undefined {
  return isJsonObject(details) && typeof details[key] === "string" ? details[key] : undefined;
}

function isJsonObject(value: JsonValue | undefined): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
