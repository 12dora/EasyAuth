import { useQuery } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { ApiError, apiRequest, type JsonObject } from "../../../../../lib/api";
import { useApiMutation } from "../../../../../lib/query";
import { USAGE_QUERY_PREFIX, USAGE_SETTINGS_URL, USAGE_STREAM_RESUME_URL } from "../useUsageData";
import type { UsageConfig, UsageSettingsPayload } from "../usageTypes";
import type { UsageFieldErrors } from "./usageSettingsForm";

export const USAGE_SETTINGS_QUERY_KEY = [...USAGE_QUERY_PREFIX, "settings"] as const;

export interface UsageSettingsSaveInput {
  config: UsageConfig;
  version: number;
}

export function useUsageSettingsQuery() {
  return useQuery({
    queryKey: USAGE_SETTINGS_QUERY_KEY,
    queryFn: ({ signal }) => apiRequest<UsageSettingsPayload>(USAGE_SETTINGS_URL, { signal }),
    retry: false,
  });
}

/** 保存后失效所有用量查询, 让概览(F2 的 useUsageSummary)立刻反映新的配额与策略。 */
export function useSaveUsageSettings(onSaved: (payload: UsageSettingsPayload) => void) {
  return useApiMutation<UsageSettingsPayload, Error, UsageSettingsSaveInput>({
    mutationFn: (input) =>
      apiRequest<UsageSettingsPayload>(USAGE_SETTINGS_URL, { method: "PUT", body: jsonBody(input) }),
    onSuccess: onSaved,
    invalidate: invalidateUsageQueries,
  });
}

export function useResumeStream() {
  return useApiMutation<unknown, Error, void>({
    mutationFn: () => apiRequest(USAGE_STREAM_RESUME_URL, { method: "POST" }),
    invalidate: invalidateUsageQueries,
  });
}

/** 概览 / 时序 / 告警 / 设置共用 F2 的 USAGE_QUERY_PREFIX, 按前缀一次性失效。 */
export function invalidateUsageQueries(client: QueryClient): void {
  void client.invalidateQueries({ queryKey: USAGE_QUERY_PREFIX });
}

/** 409: 提交所依据的版本已过期。 */
export function isVersionConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/**
 * 服务端校验失败时把 details.fields(pydantic 的 loc 用 "." 连接)映射回表单字段路径:
 * 去掉外层 "config." 前缀与列表下标, 剩下的就是本地校验用的同一套路径。
 */
export function serverFieldErrors(error: unknown): UsageFieldErrors {
  if (!(error instanceof ApiError) || typeof error.details !== "object" || error.details === null) {
    return {};
  }
  const fields = Array.isArray(error.details) ? null : error.details.fields;
  if (!Array.isArray(fields)) {
    return {};
  }
  const errors: UsageFieldErrors = {};
  for (const field of fields) {
    if (typeof field === "string" && field !== "") {
      errors[normalizeFieldPath(field)] = { key: "usageSettings.serverFieldError" };
    }
  }
  return errors;
}

function normalizeFieldPath(field: string): string {
  const withoutEnvelope = field.startsWith("config.") ? field.slice("config.".length) : field;
  return withoutEnvelope.replace(/\.\d+$/, "");
}

/**
 * 载荷本身就是纯 JSON 数据, 但共享类型是 interface(没有隐式索引签名), 无法直接匹配
 * apiRequest 的 JsonValue; 这里只做一次类型断言, 不改变任何字段。
 */
function jsonBody(input: UsageSettingsSaveInput): JsonObject {
  return input as unknown as JsonObject;
}
