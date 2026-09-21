import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { UsageAlertsPanel } from "./UsageAlertsPanel";

interface AlertsResult {
  data?: { data: unknown[] };
  isLoading: boolean;
  error: Error | null;
}

const mocks = vi.hoisted(() => ({
  alertsResult: { data: { data: [] }, isLoading: false, error: null } as {
    data?: { data: unknown[] };
    isLoading: boolean;
    error: Error | null;
  },
  summaryData: undefined as unknown,
}));

vi.mock("../useUsageData", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../useUsageData")>()),
  useUsageAlerts: () => mocks.alertsResult,
  useUsageSummary: () => ({ data: mocks.summaryData, isLoading: false, error: null }),
}));

const SUMMARY = {
  alerts: { sent_today: 1, suppressed_today: 2, daily_cap: 30, sender_ready: true, sender_problem: null, recipient_count: 3 },
};

function alertRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 9,
    kind: "threshold",
    metric: "api",
    scope: "day",
    period_key: "2026-09-21",
    threshold_percent: 80,
    status: "sent",
    title: "API daily usage at 80%",
    detail: "4000 / 5000",
    failure_reason: "",
    created_at: new Date(Date.now() - 5 * 60_000).toISOString(),
    ...overrides,
  };
}

function setAlerts(result: AlertsResult) {
  mocks.alertsResult = result;
}

describe("UsageAlertsPanel", () => {
  beforeEach(() => {
    mocks.summaryData = SUMMARY;
    setAlerts({ data: { data: [] }, isLoading: false, error: null });
  });

  test("顶部展示今日发送额度与抑制条数", () => {
    setAlerts({ data: { data: [alertRow()] }, isLoading: false, error: null });
    render(<UsageAlertsPanel />);

    expect(screen.getByText("今日已发送 1 / 上限 30")).toBeVisible();
    expect(screen.getByText("已抑制 2 条")).toBeVisible();
  });

  test("告警行展示类别、指标、阈值、状态与相对时间", () => {
    setAlerts({ data: { data: [alertRow()] }, isLoading: false, error: null });
    render(<UsageAlertsPanel />);

    expect(screen.getByText("阈值")).toBeVisible();
    expect(screen.getByText("API")).toBeVisible();
    expect(screen.getByText("80%")).toBeVisible();
    expect(screen.getByText("已发送")).toBeVisible();
    expect(screen.getByText("5 分钟前")).toBeVisible();
    expect(screen.getByText("API daily usage at 80%")).toBeVisible();
  });

  test("发送失败时给出失败原因提示", () => {
    setAlerts({
      data: { data: [alertRow({ status: "failed", failure_reason: "sender app not configured" })] },
      isLoading: false,
      error: null,
    });
    render(<UsageAlertsPanel />);

    expect(screen.getByText("发送失败")).toBeVisible();
    expect(screen.getByRole("tooltip")).toHaveTextContent("失败原因：sender app not configured");
  });

  test("没有告警时展示空状态", () => {
    render(<UsageAlertsPanel />);

    expect(screen.getByText("暂无告警")).toBeVisible();
  });

  test("加载中与加载失败各有提示", () => {
    setAlerts({ data: undefined, isLoading: true, error: null });
    const loading = render(<UsageAlertsPanel />);
    expect(screen.getByText("正在加载告警")).toBeVisible();
    loading.unmount();

    setAlerts({ data: undefined, isLoading: false, error: new Error("boom") });
    render(<UsageAlertsPanel />);
    expect(screen.getByText("告警加载失败")).toBeVisible();
    expect(screen.getByText("boom")).toBeVisible();
  });

  test("概览不可用时只隐藏额度徽标, 列表照常渲染", () => {
    mocks.summaryData = undefined;
    setAlerts({ data: { data: [alertRow()] }, isLoading: false, error: null });
    render(<UsageAlertsPanel />);

    expect(screen.queryByText("今日已发送 1 / 上限 30")).toBeNull();
    expect(screen.getByText("API daily usage at 80%")).toBeVisible();
  });
});
