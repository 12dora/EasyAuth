import { describe, expect, test } from "vitest";

import { USAGE_SEVERITY_FILL } from "./usageChartTheme";
import {
  formatUsagePercent,
  hasUsageLimit,
  sharePercent,
  usageMeterGeometry,
  usageSeverity,
  usageThresholdTicks,
} from "./usageMeterModel";
import { bucketTotal, formatBucketLabel, formatBucketTooltipLabel, hasAnyUsage } from "./usageChartModel";

describe("用量严重度与计量条几何", () => {
  test("严重度按 50 / 80 / 100 分档, 未配额视为正常", () => {
    expect(usageSeverity(null)).toBe("normal");
    expect(usageSeverity(0)).toBe("normal");
    expect(usageSeverity(49.9)).toBe("normal");
    expect(usageSeverity(50)).toBe("attention");
    expect(usageSeverity(79.9)).toBe("attention");
    expect(usageSeverity(80)).toBe("warning");
    expect(usageSeverity(99.9)).toBe("warning");
    expect(usageSeverity(100)).toBe("critical");
    expect(usageSeverity(240)).toBe("critical");
  });

  test("告警档与超限档共用 signal 红, 靠斜纹与状态文案区分(配色校验结论)", () => {
    expect(USAGE_SEVERITY_FILL.normal).not.toBe(USAGE_SEVERITY_FILL.attention);
    expect(USAGE_SEVERITY_FILL.warning).toBe(USAGE_SEVERITY_FILL.critical);
  });

  test("填充宽度封在 100%, 超出部分如实报出且不封顶", () => {
    expect(usageMeterGeometry(null)).toEqual({ fillPercent: 0, overflowPercent: 0, hasOverflow: false });
    expect(usageMeterGeometry(42.5)).toEqual({ fillPercent: 42.5, overflowPercent: 0, hasOverflow: false });
    expect(usageMeterGeometry(100)).toEqual({ fillPercent: 100, overflowPercent: 0, hasOverflow: false });
    expect(usageMeterGeometry(260)).toEqual({ fillPercent: 100, overflowPercent: 160, hasOverflow: true });
  });

  test("阈值刻度去重排序, 落在轨道外的阈值不画", () => {
    expect(usageThresholdTicks([80, 50, 100])).toEqual([50, 80, 100]);
    expect(usageThresholdTicks([50, 50, 120, 0, -1])).toEqual([50]);
    expect(usageThresholdTicks(null)).toEqual([]);
  });

  test("hasUsageLimit 只认正整数上限", () => {
    expect(hasUsageLimit(null)).toBe(false);
    expect(hasUsageLimit(0)).toBe(false);
    expect(hasUsageLimit(5000)).toBe(true);
  });

  test("百分比文案小数位随量级收敛, 占比按总量归一", () => {
    expect(formatUsagePercent(8.24)).toBe("8.2%");
    expect(formatUsagePercent(63.4)).toBe("63%");
    expect(sharePercent(25, 100)).toBe(25);
    expect(sharePercent(5, 0)).toBe(0);
  });
});

describe("趋势图数据整形", () => {
  test("刻度文案按粒度取字面字段, 不做时区换算", () => {
    expect(formatBucketLabel("2026-09-21T14:00:00+08:00", "hour")).toBe("14:00");
    expect(formatBucketLabel("2026-09-21T00:00:00+08:00", "day")).toBe("09-21");
    expect(formatBucketTooltipLabel("2026-09-21T14:00:00+08:00", "hour")).toBe("09-21 14:00");
    expect(formatBucketTooltipLabel("2026-09-21T00:00:00+08:00", "day")).toBe("2026-09-21");
  });

  test("桶合计不含被拒绝的调用, 但空态判定要看被拒绝", () => {
    const point = {
      start: "2026-09-21T14:00:00+08:00",
      api_billed: 3,
      api_unbilled: 1,
      internal: 2,
      webhook: 4,
      stream: 5,
      blocked: 7,
    };
    expect(bucketTotal(point)).toBe(15);
    expect(hasAnyUsage([{ ...point, api_billed: 0, api_unbilled: 0, internal: 0, webhook: 0, stream: 0 }])).toBe(true);
    expect(hasAnyUsage([{ ...point, api_billed: 0, api_unbilled: 0, internal: 0, webhook: 0, stream: 0, blocked: 0 }])).toBe(
      false,
    );
  });
});
