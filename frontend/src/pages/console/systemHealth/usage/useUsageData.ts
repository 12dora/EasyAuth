import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiRequest } from "../../../../lib/api";
import type { UsageRange } from "./usageRange";
import type { UsageAlertsPayload, UsageSummaryPayload, UsageTimeseriesPayload } from "./usageTypes";

const USAGE_API_BASE = "/console/api/v1/operations/system-health/usage";

export const USAGE_SUMMARY_URL = `${USAGE_API_BASE}/summary`;
export const USAGE_TIMESERIES_URL = `${USAGE_API_BASE}/timeseries`;
export const USAGE_ALERTS_URL = `${USAGE_API_BASE}/alerts`;
export const USAGE_SETTINGS_URL = `${USAGE_API_BASE}/settings`;
export const USAGE_STREAM_RESUME_URL = `${USAGE_API_BASE}/stream/resume`;

/** 所有用量查询共用的前缀, 设置保存后按前缀整体失效(F3 使用)。 */
export const USAGE_QUERY_PREFIX = ["console", "usage"] as const;

export const USAGE_SUMMARY_QUERY_KEY = [...USAGE_QUERY_PREFIX, "summary"] as const;

/** 概览每 30 秒自动刷新一次: 与后端 60 秒的评估节拍同量级, 页面不会看到陈旧的限流状态。 */
export const USAGE_SUMMARY_REFETCH_MS = 30_000;

export const USAGE_ALERTS_DEFAULT_LIMIT = 50;

export function usageTimeseriesUrl(range: UsageRange): string {
  const query = new URLSearchParams({ from: range.from, to: range.to });
  return `${USAGE_TIMESERIES_URL}?${query.toString()}`;
}

export function usageAlertsUrl(limit: number): string {
  return `${USAGE_ALERTS_URL}?${new URLSearchParams({ limit: String(limit) }).toString()}`;
}

export function useUsageSummary() {
  return useQuery({
    queryKey: USAGE_SUMMARY_QUERY_KEY,
    queryFn: ({ signal }) => apiRequest<UsageSummaryPayload>(USAGE_SUMMARY_URL, { signal }),
    refetchInterval: USAGE_SUMMARY_REFETCH_MS,
    // 后台标签页不必继续轮询: 回到前台时 react-query 会立刻按 staleTime 重新取一次。
    refetchIntervalInBackground: false,
    retry: false,
  });
}

/**
 * 时间序列。粒度交给后端按区间长度决定(<= 2 天按小时, 否则按天),
 * 前端只读响应里的 `granularity`, 不在两处各判一次。
 */
export function useUsageTimeseries(range: UsageRange) {
  return useQuery({
    queryKey: [...USAGE_QUERY_PREFIX, "timeseries", range.from, range.to],
    queryFn: ({ signal }) => apiRequest<UsageTimeseriesPayload>(usageTimeseriesUrl(range), { signal }),
    // 切区间时保留上一份图表: 卡片不塌, 由 isFetching 降低不透明度表示在刷新。
    placeholderData: keepPreviousData,
    retry: false,
  });
}

export function useUsageAlerts(limit: number = USAGE_ALERTS_DEFAULT_LIMIT) {
  return useQuery({
    queryKey: [...USAGE_QUERY_PREFIX, "alerts", limit],
    queryFn: ({ signal }) => apiRequest<UsageAlertsPayload>(usageAlertsUrl(limit), { signal }),
    retry: false,
  });
}
