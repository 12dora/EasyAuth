import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import {
  USAGE_ALERTS_URL,
  USAGE_QUERY_PREFIX,
  USAGE_SUMMARY_QUERY_KEY,
  USAGE_SUMMARY_REFETCH_MS,
  USAGE_SUMMARY_URL,
  USAGE_TIMESERIES_URL,
  usageAlertsUrl,
  usageTimeseriesUrl,
  useUsageAlerts,
  useUsageSummary,
  useUsageTimeseries,
} from "./useUsageData";

describe("用量监控数据 hooks", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  test("接口地址挂在 system-health/usage 下", () => {
    expect(USAGE_SUMMARY_URL).toBe("/console/api/v1/operations/system-health/usage/summary");
    expect(USAGE_TIMESERIES_URL).toBe("/console/api/v1/operations/system-health/usage/timeseries");
    expect(USAGE_ALERTS_URL).toBe("/console/api/v1/operations/system-health/usage/alerts");
  });

  test("时间序列按本地日历日传 from/to, 粒度交给后端决定", () => {
    expect(usageTimeseriesUrl({ key: "custom", from: "2026-09-01", to: "2026-09-05" })).toBe(
      `${USAGE_TIMESERIES_URL}?from=2026-09-01&to=2026-09-05`,
    );
    expect(usageAlertsUrl(20)).toBe(`${USAGE_ALERTS_URL}?limit=20`);
  });

  test("概览按固定 key 缓存", async () => {
    const fetchMock = stubFetch({ generated_at: "2026-09-21T10:00:00+08:00", metrics: [] });
    const client = newClient();

    renderHook(() => useUsageSummary(), { wrapper: wrapperFor(client) });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(USAGE_SUMMARY_URL, expect.objectContaining({ credentials: "include" }));
    });
    expect(client.getQueryCache().find({ queryKey: USAGE_SUMMARY_QUERY_KEY })).toBeDefined();
  });

  test("概览满 30 秒真的再取一次, 卸载后不再轮询", async () => {
    expect(USAGE_SUMMARY_REFETCH_MS).toBe(30_000);
    vi.useFakeTimers();
    const fetchMock = stubFetch({ generated_at: "2026-09-21T10:00:00+08:00", metrics: [] });
    const view = renderHook(() => useUsageSummary(), { wrapper: wrapperFor(newClient()) });

    await flushTimers(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // 差一点还不该发第二次, 满 30 秒才发。
    await flushTimers(USAGE_SUMMARY_REFETCH_MS - 1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await flushTimers(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    view.unmount();
    await flushTimers(USAGE_SUMMARY_REFETCH_MS * 3);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("告警列表与概览同一个 30 秒节拍", async () => {
    vi.useFakeTimers();
    const fetchMock = stubFetch({ data: [] });
    const view = renderHook(() => useUsageAlerts(10), { wrapper: wrapperFor(newClient()) });

    await flushTimers(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await flushTimers(USAGE_SUMMARY_REFETCH_MS);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    view.unmount();
    await flushTimers(USAGE_SUMMARY_REFETCH_MS * 3);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("时间序列与告警各自带区间/条数进 queryKey", async () => {
    const fetchMock = stubFetch({ data: [], points: [], categories: [] });
    const client = newClient();
    const range = { key: "custom", from: "2026-09-01", to: "2026-09-05" } as const;

    renderHook(
      () => {
        useUsageTimeseries(range);
        useUsageAlerts(10);
      },
      { wrapper: wrapperFor(client) },
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(usageTimeseriesUrl(range), expect.anything());
      expect(fetchMock).toHaveBeenCalledWith(usageAlertsUrl(10), expect.anything());
    });
    const keys = client
      .getQueryCache()
      .getAll()
      .map((query) => query.queryKey);
    expect(keys).toContainEqual([...USAGE_QUERY_PREFIX, "timeseries", "2026-09-01", "2026-09-05"]);
    expect(keys).toContainEqual([...USAGE_QUERY_PREFIX, "alerts", 10]);
  });
});

/** 推进假时钟并把随之而来的 promise 回调一起冲干净, 免得 react-query 的状态更新落在 act 外。 */
async function flushTimers(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function newClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn<typeof fetch>(
    async () =>
      new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
