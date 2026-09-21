import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { UsageMeterCard } from "./UsageMeterCard";
import type { UsageMetricKey, UsageMetricSummary } from "./usageTypes";

// F3 的设置入口在用例里只需要一个可断言的占位, 真实弹窗由 F3 自己的用例覆盖。
vi.mock("./settings/UsageSettingsButton", () => ({
  default: ({ variant }: { variant?: string }) => <button type="button">settings:{variant ?? "primary"}</button>,
}));

describe("UsageMeterCard", () => {
  test("渲染大数字、两条计量条与每个告警阈值的刻度", () => {
    render(<UsageMeterCard metric={metricSummary()} />);

    expect(screen.getByText("API 计费调用")).toBeInTheDocument();
    expect(screen.getByTestId("usage-count-up")).toHaveTextContent("4,120");

    // role="meter" 而不是 progressbar: 这是一个当前值, 不是一件正在推进的任务。
    const bars = screen.getAllByRole("meter");
    expect(bars).toHaveLength(2);
    expect(bars[0]).toHaveAttribute("aria-label", "API 计费调用 今日用量 82%");
    expect(bars[0]).toHaveAttribute("aria-valuemax", "5000");
    expect(bars[0]).toHaveAttribute("aria-valuenow", "4120");
    expect(bars[0]).toHaveAttribute("aria-valuetext", "82%");
    expect(bars[0]).toHaveStyle({ width: "82.4%" });

    // 两条条各三个阈值刻度, 每个刻度都能悬浮读出它代表的百分比。
    expect(screen.getAllByTestId("usage-threshold-tick")).toHaveLength(6);
    expect(screen.getAllByTitle("80% 告警阈值")).toHaveLength(2);
  });

  test("按 next_threshold 给出「还可调用 N 次」的提示与月底预计", () => {
    render(<UsageMeterCard metric={metricSummary()} />);

    expect(screen.getByText("还可调用 880 次后触发日上限 100% 告警")).toBeInTheDocument();
    expect(screen.getByText("按当前速度月底预计 130,300")).toBeInTheDocument();
  });

  test("所有阈值都触发过时改口径, 不再显示一个假的剩余次数", () => {
    render(<UsageMeterCard metric={metricSummary({ next_threshold: null })} />);
    expect(screen.getByText("所有告警阈值都已触发")).toBeInTheDocument();
  });

  test("超过 100% 时报出超出的幅度而不是封顶的百分比", () => {
    render(
      <UsageMeterCard
        metric={metricSummary({
          today: { used: 6000, cap: 5000, remaining: 0, percent: 120 },
          enforcement: { state: "blocked", reason: "daily_cap", since: "2026-09-21T10:00:00+08:00" },
        })}
      />,
    );

    expect(screen.getByText("已超出额度 20%")).toBeInTheDocument();
    expect(screen.getByText("已拦截计费调用")).toBeInTheDocument();

    // aria-valuenow 必须落在 min..max 之间, 超出多少由 aria-valuetext 如实报读。
    const todayBar = screen.getAllByRole("meter")[0];
    expect(todayBar).toHaveAttribute("aria-valuemax", "5000");
    expect(todayBar).toHaveAttribute("aria-valuenow", "5000");
    expect(todayBar).toHaveAttribute("aria-valuetext", "6,000 / 5,000，已超出额度 20%");
  });

  test("未设置任何配额时走空态, 并给出打开用量设置的入口", () => {
    render(
      <UsageMeterCard
        metric={metricSummary({
          metric: "stream",
          today: { used: 12, cap: null, remaining: null, percent: null },
          month: {
            used: 40,
            quota: null,
            remaining: null,
            percent: null,
            period_start: "2026-09-01",
            period_end: "2026-09-30",
            projected: null,
          },
          next_threshold: null,
        })}
      />,
    );

    expect(screen.getByText("未设置配额")).toBeInTheDocument();
    expect(screen.queryAllByRole("meter")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "settings:inline" })).toBeInTheDocument();
  });
});

function metricSummary(overrides: Partial<UsageMetricSummary> = {}): UsageMetricSummary {
  const metric: UsageMetricKey = overrides.metric ?? "api";
  return {
    metric,
    policy: "degrade",
    today: { used: 4120, cap: 5000, remaining: 880, percent: 82.4 },
    month: {
      used: 91_200,
      quota: 500_000,
      remaining: 408_800,
      percent: 18.24,
      period_start: "2026-09-01",
      period_end: "2026-09-30",
      projected: 130_300,
    },
    enforcement: { state: "normal", reason: null, since: null },
    thresholds_percent: [50, 80, 100],
    next_threshold: { scope: "day", percent: 100, remaining: 880 },
    blocked_today: 0,
    last_hour: 37,
    ...overrides,
  };
}
