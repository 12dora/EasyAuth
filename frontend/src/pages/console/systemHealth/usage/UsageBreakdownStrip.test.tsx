import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import { UsageBreakdownStrip } from "./UsageBreakdownStrip";

describe("UsageBreakdownStrip", () => {
  test("分段宽度按各自占总调用的比例, 图例把数值直接写出来", () => {
    render(<UsageBreakdownStrip breakdown={{ total: 1000, billed: 500, unbilled: 200, internal: 300 }} />);

    expect(screen.getByTestId("usage-breakdown-billed")).toHaveStyle({ width: "50%" });
    expect(screen.getByTestId("usage-breakdown-unbilled")).toHaveStyle({ width: "20%" });
    expect(screen.getByTestId("usage-breakdown-internal")).toHaveStyle({ width: "30%" });

    expect(screen.getByText("1,000")).toBeInTheDocument();
    expect(screen.getByText("计费 500 · 50%")).toBeInTheDocument();
    expect(screen.getByText("不计费（钉钉） 200 · 20%")).toBeInTheDocument();
    expect(screen.getByText("内部调用 300 · 30%")).toBeInTheDocument();
  });

  test("为 0 的分段不画一条零宽的色块, 但图例仍然列出它", () => {
    render(<UsageBreakdownStrip breakdown={{ total: 800, billed: 600, unbilled: 200, internal: 0 }} />);

    expect(screen.queryByTestId("usage-breakdown-internal")).not.toBeInTheDocument();
    expect(screen.getByText("内部调用 0 · 0%")).toBeInTheDocument();
    expect(screen.getByTestId("usage-breakdown-billed")).toHaveStyle({ width: "75%" });
  });

  test("今天还没有调用时给一句话空态, 不画空条", () => {
    render(<UsageBreakdownStrip breakdown={{ total: 0, billed: 0, unbilled: 0, internal: 0 }} />);

    expect(screen.getByText("今日还没有 API 调用。")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
