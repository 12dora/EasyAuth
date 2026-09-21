import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../../../components/antd/testing";
import UsageMonitorTab from "./UsageMonitorTab";
import { formatLocalDate } from "./usage/usageRange";
import type { UsageSummaryPayload, UsageTimeseriesPayload } from "./usage/usageTypes";

vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

// recharts 在独立的异步 chunk 里, 用例只验证「图表拿到了这一区间的数据」, 不渲染真实图表。
vi.mock("./usage/UsageTrendChart", () => ({
  UsageTrendChart: ({ data }: { data: UsageTimeseriesPayload | undefined }) => (
    <div data-testid="trend-chart">{data ? `${data.from}~${data.to}:${data.granularity}` : "loading"}</div>
  ),
}));

// F3 的三个组件由 F3 自己的用例覆盖, 这里只确认它们被挂在了正确的位置。
vi.mock("./usage/settings/UsageSettingsButton", () => ({
  default: ({ variant }: { variant?: string }) => <button type="button">settings:{variant ?? "primary"}</button>,
}));
vi.mock("./usage/settings/UsageAlertsPanel", () => ({
  UsageAlertsPanel: () => <div data-testid="alerts-panel" />,
}));
vi.mock("./usage/settings/StreamPausedBanner", () => ({
  StreamPausedBanner: () => <div data-testid="stream-banner" />,
}));

const TODAY = formatLocalDate(new Date());
const SUMMARY_URL = "/console/api/v1/operations/system-health/usage/summary";
const TIMESERIES_URL = `/console/api/v1/operations/system-health/usage/timeseries?from=${TODAY}&to=${TODAY}`;

describe("UsageMonitorTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("默认按今天取数, 三张计量卡、构成条、趋势图与分类表都落位", async () => {
    stubUsageApi();
    renderTab();

    await waitFor(() => {
      expect(screen.getByText("API 计费调用")).toBeInTheDocument();
    });
    expect(screen.getByText("Webhook 回调")).toBeInTheDocument();
    expect(screen.getByText("Stream 事件")).toBeInTheDocument();
    expect(screen.getByText("计费 412 · 69%")).toBeInTheDocument();
    expect(screen.getByTestId("stream-banner")).toBeInTheDocument();
    expect(screen.getByTestId("alerts-panel")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "settings:primary" })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("trend-chart")).toHaveTextContent(`${TODAY}~${TODAY}:hour`);
    });
    expect(await screen.findByText("工作通知发送")).toBeInTheDocument();
  });

  test("切换快捷区间会写回 URL 并按新区间重新取数", async () => {
    const fetchMock = stubUsageApi();
    const user = userEvent.setup();
    renderTab();

    await waitFor(() => expect(screen.getByText("API 计费调用")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "本月" }));

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("range=month");
    });
    await waitFor(() => {
      const monthStart = `${TODAY.slice(0, 7)}-01`;
      expect(fetchMock).toHaveBeenCalledWith(
        `/console/api/v1/operations/system-health/usage/timeseries?from=${monthStart}&to=${TODAY}`,
        expect.anything(),
      );
    });
  });

  test("Authentik 数据滞后时给出横幅, 但不影响其余内容", async () => {
    stubUsageApi({
      authentik: { pulled_at: "2026-09-21T09:00:00+08:00", stale: true, error: null },
    });
    renderTab();

    expect(await screen.findByText("Authentik 用量数据滞后")).toBeInTheDocument();
    expect(screen.getByText("API 计费调用")).toBeInTheDocument();
  });

  test("概览接口失败且没有可用数据时整块降级为可重试的失败态", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({ error: { code: "SERVER_ERROR", message: "服务器内部错误" } }, 500),
      ),
    );
    renderTab();

    expect(await screen.findByText("用量数据加载失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /重新加载/ })).toBeInTheDocument();
  });
});

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderWithAntd(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/operations/system-health?tab=usage"]}>
        <LocationSearch />
        <UsageMonitorTab />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationSearch() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}

function stubUsageApi(summaryOverrides: Partial<UsageSummaryPayload> = {}) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url === SUMMARY_URL) {
      return jsonResponse({ ...summaryPayload(), ...summaryOverrides });
    }
    if (url.startsWith("/console/api/v1/operations/system-health/usage/timeseries")) {
      return jsonResponse(timeseriesPayload(url));
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}

function summaryPayload(): UsageSummaryPayload {
  return {
    generated_at: "2026-09-21T10:00:00+08:00",
    timezone: "Asia/Shanghai",
    metrics: [
      metric("api", { used: 412, cap: 5000, remaining: 4588, percent: 8.24 }),
      metric("webhook", { used: 90, cap: null, remaining: null, percent: null }),
      metric("stream", { used: 12, cap: null, remaining: null, percent: null }),
    ],
    api_breakdown_today: { total: 600, billed: 412, unbilled: 60, internal: 128 },
    alerts: {
      sent_today: 1,
      suppressed_today: 0,
      daily_cap: 30,
      sender_ready: true,
      sender_problem: null,
      recipient_count: 3,
    },
    stream: { paused: false, paused_at: null, can_resume: false },
    authentik: { pulled_at: "2026-09-21T09:59:00+08:00", stale: false, error: null },
  };
}

function metric(
  key: "api" | "webhook" | "stream",
  today: UsageSummaryPayload["metrics"][number]["today"],
): UsageSummaryPayload["metrics"][number] {
  return {
    metric: key,
    policy: key === "api" ? "degrade" : "alert_only",
    today,
    month: {
      used: 9120,
      quota: key === "stream" ? null : 500_000,
      remaining: key === "stream" ? null : 490_880,
      percent: key === "stream" ? null : 1.82,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      projected: key === "stream" ? null : 13_030,
    },
    enforcement: { state: "normal", reason: null, since: null },
    thresholds_percent: [50, 80, 100],
    next_threshold: { scope: "day", percent: 50, remaining: 2088 },
    blocked_today: 0,
    last_hour: 37,
  };
}

function timeseriesPayload(url: string): UsageTimeseriesPayload {
  const params = new URLSearchParams(url.slice(url.indexOf("?")));
  return {
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    granularity: "hour",
    points: [
      {
        start: "2026-09-21T09:00:00+08:00",
        api_billed: 12,
        api_unbilled: 3,
        internal: 5,
        webhook: 2,
        stream: 4,
        blocked: 0,
      },
    ],
    totals: { api_billed: 12, api_unbilled: 3, internal: 5, webhook: 2, stream: 4, blocked: 0 },
    categories: [
      {
        metric: "api",
        category: "notify_send",
        label: "工作通知发送",
        source: "easyauth",
        billed: true,
        priority: "p1",
        count: 12,
        blocked: 0,
      },
    ],
  };
}
