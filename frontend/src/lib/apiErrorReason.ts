import { ApiError } from "./api";

/**
 * 后端细错误码落在 error.details.reason（01 §6.1）。
 * 禁止用 error.code 分支业务细码：code 只有 9 个大写粗分类。
 */
export function apiErrorReason(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) {
    return undefined;
  }
  const details = error.details;
  if (details === null || details === undefined || typeof details !== "object" || Array.isArray(details)) {
    return undefined;
  }
  const reason = (details as { reason?: unknown }).reason;
  return typeof reason === "string" ? reason : undefined;
}
