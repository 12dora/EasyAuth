import { screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../../../../components/antd/testing";
import { UsageCategoryTable, sortUsageCategories } from "./UsageCategoryTable";
import type { UsageCategoryTotal } from "./usageTypes";

// antd Table 在 jsdom 下重建整棵表格很慢, 与其它表格用例统一到同一档超时。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

describe("UsageCategoryTable", () => {
  test("按调用次数降序排列, 次数相同按分类键定序", () => {
    const sorted = sortUsageCategories([
      category({ category: "probe", count: 12 }),
      category({ category: "notify_send", count: 300 }),
      category({ category: "ak_login", count: 300 }),
      category({ category: "approval", count: 41 }),
    ]);

    expect(sorted.map((row) => row.category)).toEqual(["ak_login", "notify_send", "approval", "probe"]);
  });

  test("表格按次数降序渲染, 并给出来源 / 计费 / 优先级徽标与占比", () => {
    renderWithAntd(
      <UsageCategoryTable
        categories={[
          category({ category: "probe", label_zh: "连通性探测", count: 25, billed: false, priority: "p2" }),
          category({
            category: "ak_login",
            label_zh: "登录",
            source: "authentik",
            count: 75,
            priority: "p0",
            blocked: 3,
          }),
        ]}
        isLoading={false}
      />,
    );

    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]).getByText("登录")).toBeInTheDocument();
    expect(within(rows[0]).getByText("Authentik")).toBeInTheDocument();
    expect(within(rows[0]).getByText("P0")).toBeInTheDocument();
    expect(within(rows[0]).getByText("75%")).toBeInTheDocument();
    expect(within(rows[0]).getByText("3")).toBeInTheDocument();

    expect(within(rows[1]).getByText("连通性探测")).toBeInTheDocument();
    expect(within(rows[1]).getByText("不计费")).toBeInTheDocument();
    expect(within(rows[1]).getByText("25%")).toBeInTheDocument();
  });

  test("后端没给 label 时回落 label_zh, 再不行用分类键", () => {
    renderWithAntd(
      <UsageCategoryTable
        categories={[category({ category: "internal_netbird", label_zh: "", label_en: "", count: 4 })]}
        isLoading={false}
      />,
    );

    expect(screen.getAllByText("internal_netbird").length).toBeGreaterThan(0);
  });

  test("区间内没有分类数据时走表格空态", () => {
    renderWithAntd(<UsageCategoryTable categories={[]} isLoading={false} />);
    expect(screen.getByText("所选区间没有分类数据")).toBeInTheDocument();
  });
});

function category(overrides: Partial<UsageCategoryTotal> = {}): UsageCategoryTotal {
  return {
    metric: "api",
    category: "notify_send",
    label_zh: "工作通知发送",
    label_en: "Work notice",
    source: "easyauth",
    billed: true,
    priority: "p1",
    count: 10,
    blocked: 0,
    ...overrides,
  };
}
