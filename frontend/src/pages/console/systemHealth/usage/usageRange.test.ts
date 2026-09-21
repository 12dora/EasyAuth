import { describe, expect, test } from "vitest";

import {
  DEFAULT_USAGE_RANGE_KEY,
  formatLocalDate,
  resolveUsageRange,
  usageRangeDayCount,
  usageRangeFromSearchParams,
  usageRangeSearchUpdates,
} from "./usageRange";

// 2026-09-23 是周三, 本周一是 09-21; 用下午的时刻确保不会有「当天算成昨天」的时区错位。
const WEDNESDAY = new Date(2026, 8, 23, 14, 30, 0);
// 2026-09-20 是周日, 按「周一为一周开始」它属于 09-14 那一周。
const SUNDAY = new Date(2026, 8, 20, 0, 30, 0);

describe("用量监控时间范围", () => {
  test("formatLocalDate 取本地日历日, 不做 UTC 换算", () => {
    expect(formatLocalDate(new Date(2026, 0, 1, 23, 59, 59))).toBe("2026-01-01");
    expect(formatLocalDate(new Date(2026, 8, 5, 0, 0, 0))).toBe("2026-09-05");
  });

  test("今天 / 昨天是单日区间", () => {
    expect(resolveUsageRange("today", "", "", WEDNESDAY)).toEqual({
      key: "today",
      from: "2026-09-23",
      to: "2026-09-23",
    });
    expect(resolveUsageRange("yesterday", "", "", WEDNESDAY)).toEqual({
      key: "yesterday",
      from: "2026-09-22",
      to: "2026-09-22",
    });
  });

  test("本周从周一开始, 周日归到上一周", () => {
    expect(resolveUsageRange("week", "", "", WEDNESDAY)).toEqual({
      key: "week",
      from: "2026-09-21",
      to: "2026-09-23",
    });
    expect(resolveUsageRange("week", "", "", SUNDAY)).toEqual({
      key: "week",
      from: "2026-09-14",
      to: "2026-09-20",
    });
  });

  test("本月到今天为止, 上月是完整自然月", () => {
    expect(resolveUsageRange("month", "", "", WEDNESDAY)).toEqual({
      key: "month",
      from: "2026-09-01",
      to: "2026-09-23",
    });
    expect(resolveUsageRange("last_month", "", "", WEDNESDAY)).toEqual({
      key: "last_month",
      from: "2026-08-01",
      to: "2026-08-31",
    });
  });

  test("上月跨年与跨闰月都落在自然月边界上", () => {
    expect(resolveUsageRange("last_month", "", "", new Date(2026, 0, 9))).toEqual({
      key: "last_month",
      from: "2025-12-01",
      to: "2025-12-31",
    });
    expect(resolveUsageRange("last_month", "", "", new Date(2028, 2, 5))).toEqual({
      key: "last_month",
      from: "2028-02-01",
      to: "2028-02-29",
    });
  });

  test("自定义区间起止写反时对调, 缺端时回落默认区间", () => {
    expect(resolveUsageRange("custom", "2026-09-10", "2026-09-01", WEDNESDAY)).toEqual({
      key: "custom",
      from: "2026-09-01",
      to: "2026-09-10",
    });
    expect(resolveUsageRange("custom", "2026-09-10", "", WEDNESDAY)).toEqual({
      key: DEFAULT_USAGE_RANGE_KEY,
      from: "2026-09-23",
      to: "2026-09-23",
    });
  });

  test("URL 查询串解析: 未知 range 回落今天, custom 读 from/to", () => {
    expect(usageRangeFromSearchParams(new URLSearchParams("range=week"), WEDNESDAY).from).toBe("2026-09-21");
    expect(usageRangeFromSearchParams(new URLSearchParams("range=nope"), WEDNESDAY)).toEqual({
      key: "today",
      from: "2026-09-23",
      to: "2026-09-23",
    });
    expect(
      usageRangeFromSearchParams(
        new URLSearchParams("range=custom&from=2026-09-01&to=2026-09-05"),
        WEDNESDAY,
      ),
    ).toEqual({ key: "custom", from: "2026-09-01", to: "2026-09-05" });
  });

  test("写回 URL 时快捷区间清掉 from/to", () => {
    expect(usageRangeSearchUpdates("month")).toEqual({ range: "month", from: "", to: "" });
    expect(usageRangeSearchUpdates("custom", "2026-09-01", "2026-09-05")).toEqual({
      range: "custom",
      from: "2026-09-01",
      to: "2026-09-05",
    });
  });

  test("区间天数含端点", () => {
    expect(usageRangeDayCount({ key: "today", from: "2026-09-23", to: "2026-09-23" })).toBe(1);
    expect(usageRangeDayCount({ key: "custom", from: "2026-08-01", to: "2026-08-31" })).toBe(31);
  });
});
