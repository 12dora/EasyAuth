import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { UsageRangeFilter } from "./UsageRangeFilter";
import type { UsageRange } from "./usageRange";

interface StubRangeValue {
  from: string;
  to: string;
}

/**
 * 真正的 DateRangeControl 是懒加载的 antd RangePicker; 用例要的是"它回调了什么",
 * 所以换成一个能按需打出半截区间 / 超长区间的桩, 顺便把当前 value 暴露出来。
 */
vi.mock("../../../../components/antd/AppTable", () => ({
  DateRangeControl: ({
    value,
    onChange,
  }: {
    value: StubRangeValue;
    onChange: (next: StubRangeValue) => void;
  }) => (
    <div>
      <span data-testid="picker-value">{`${value.from}|${value.to}`}</span>
      <button type="button" onClick={() => onChange({ from: "2026-09-01T00:00:00+08:00", to: "" })}>
        pick-start-only
      </button>
      <button
        type="button"
        onClick={() => onChange({ from: "2026-09-01T00:00:00+08:00", to: "2026-09-05T23:59:59+08:00" })}
      >
        pick-both
      </button>
      <button
        type="button"
        onClick={() => onChange({ from: "2024-01-01T00:00:00+08:00", to: "2026-09-05T23:59:59+08:00" })}
      >
        pick-too-long
      </button>
      <button type="button" onClick={() => onChange({ from: "", to: "" })}>
        pick-clear
      </button>
    </div>
  ),
}));

const RANGE: UsageRange = { key: "today", from: "2026-09-21", to: "2026-09-21" };

describe("UsageRangeFilter 自定义区间", () => {
  test("只选了开始日期时不写 URL, 选择器停在半截区间上而不是弹回今天", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UsageRangeFilter onChange={onChange} range={RANGE} />);

    await user.click(screen.getByRole("button", { name: "pick-start-only" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByTestId("picker-value")).toHaveTextContent("2026-09-01|");
  });

  test("两端都选好后才写回 custom 区间", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UsageRangeFilter onChange={onChange} range={RANGE} />);

    await user.click(screen.getByRole("button", { name: "pick-start-only" }));
    await user.click(screen.getByRole("button", { name: "pick-both" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("custom", "2026-09-01", "2026-09-05");
    // 写回 URL 后重新跟随 range, 本地草稿让位。
    expect(screen.getByTestId("picker-value")).toHaveTextContent("2026-09-21|2026-09-21");
  });

  test("跨度超过 400 天时就地报错并拒绝发请求", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UsageRangeFilter onChange={onChange} range={RANGE} />);

    await user.click(screen.getByRole("button", { name: "pick-too-long" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("自定义区间最长 400 天");
    expect(screen.getByTestId("picker-value")).toHaveTextContent("2024-01-01|2026-09-05");
  });

  test("超长提示在改用快捷区间后消失", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UsageRangeFilter onChange={onChange} range={RANGE} />);

    await user.click(screen.getByRole("button", { name: "pick-too-long" }));
    await user.click(screen.getByRole("button", { name: "本月" }));

    expect(onChange).toHaveBeenCalledWith("month");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByTestId("picker-value")).toHaveTextContent("2026-09-21|2026-09-21");
  });

  test("两端都清空回到默认区间", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<UsageRangeFilter onChange={onChange} range={RANGE} />);

    await user.click(screen.getByRole("button", { name: "pick-clear" }));

    expect(onChange).toHaveBeenCalledWith("today");
  });
});
