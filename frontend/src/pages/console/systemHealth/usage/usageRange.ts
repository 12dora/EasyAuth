/**
 * 用量监控的时间范围: 快捷区间 + 自定义区间, 状态放在 URL 查询串里
 * (`range=today|yesterday|week|month|last_month|custom&from&to`)。
 *
 * 全部按浏览器本地日历日计算, 周一为一周的开始; 与后端 `from`/`to`(本地日历日, 含端点)
 * 口径一致, 因此这里只产出 `YYYY-MM-DD`, 不做任何时区换算。
 */

export const USAGE_RANGE_PARAM = "range";
export const USAGE_RANGE_FROM_PARAM = "from";
export const USAGE_RANGE_TO_PARAM = "to";

export const USAGE_QUICK_RANGE_KEYS = ["today", "yesterday", "week", "month", "last_month"] as const;

export type UsageQuickRangeKey = (typeof USAGE_QUICK_RANGE_KEYS)[number];

export type UsageRangeKey = UsageQuickRangeKey | "custom";

export interface UsageRange {
  key: UsageRangeKey;
  /** 本地日历日, 含端点。 */
  from: string;
  to: string;
}

/** 默认区间必须是快捷区间: 自定义区间解析失败时会回落到它, 类型上先断掉递归的可能。 */
export const DEFAULT_USAGE_RANGE_KEY: UsageQuickRangeKey = "today";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** 后端对时间序列区间的硬上限(契约 §4), 超过直接 400; 前端先拦一道并给出说明。 */
export const USAGE_RANGE_MAX_DAYS = 400;

/** 是否是 `YYYY-MM-DD` 形态的日历日。 */
export function isCalendarDay(value: string): boolean {
  return ISO_DATE.test(value);
}

/** 本地日历日字符串; 不用 toISOString(), 那会把本地日期挪到 UTC 当天。 */
export function formatLocalDate(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function addDays(date: Date, days: number): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

/** 周一为一周的第一天: JS 的 getDay() 周日是 0, 先折算成 0=周一。 */
function startOfWeek(date: Date): Date {
  const mondayIndex = (date.getDay() + 6) % 7;
  return addDays(date, -mondayIndex);
}

export function isUsageRangeKey(value: string | null): value is UsageRangeKey {
  return value === "custom" || USAGE_QUICK_RANGE_KEYS.some((key) => key === value);
}

function quickRangeBounds(key: UsageQuickRangeKey, now: Date): { from: Date; to: Date } {
  const today = startOfDay(now);
  switch (key) {
    case "today":
      return { from: today, to: today };
    case "yesterday": {
      const yesterday = addDays(today, -1);
      return { from: yesterday, to: yesterday };
    }
    case "week":
      return { from: startOfWeek(today), to: today };
    case "month":
      return { from: new Date(today.getFullYear(), today.getMonth(), 1), to: today };
    case "last_month": {
      const firstOfThisMonth = new Date(today.getFullYear(), today.getMonth(), 1);
      return { from: new Date(today.getFullYear(), today.getMonth() - 1, 1), to: addDays(firstOfThisMonth, -1) };
    }
  }
}

/**
 * 把「区间键 + 自定义起止」解析成确定的日历日区间。
 *
 * 自定义区间缺少任何一端都不是合法状态(后端 `from`/`to` 都必填),
 * 因此回落到默认的「今天」, 而不是自己补一个端点。
 */
export function resolveUsageRange(
  key: UsageRangeKey,
  from: string,
  to: string,
  now: Date = new Date(),
): UsageRange {
  if (key === "custom") {
    if (!isCalendarDay(from) || !isCalendarDay(to)) {
      return resolveUsageRange(DEFAULT_USAGE_RANGE_KEY, "", "", now);
    }
    // 起止写反时直接对调, 避免把一个空区间发给后端。
    return from <= to ? { key, from, to } : { key, from: to, to: from };
  }
  const bounds = quickRangeBounds(key, now);
  return { key, from: formatLocalDate(bounds.from), to: formatLocalDate(bounds.to) };
}

export function usageRangeFromSearchParams(params: URLSearchParams, now: Date = new Date()): UsageRange {
  const raw = params.get(USAGE_RANGE_PARAM);
  const key = isUsageRangeKey(raw) ? raw : DEFAULT_USAGE_RANGE_KEY;
  return resolveUsageRange(
    key,
    params.get(USAGE_RANGE_FROM_PARAM) ?? "",
    params.get(USAGE_RANGE_TO_PARAM) ?? "",
    now,
  );
}

/** 写回 URL 的查询参数; 空字符串由调用方删键(与运营页的 updateSearchParams 约定一致)。 */
export function usageRangeSearchUpdates(key: UsageRangeKey, from = "", to = ""): Record<string, string> {
  if (key === "custom") {
    return { [USAGE_RANGE_PARAM]: "custom", [USAGE_RANGE_FROM_PARAM]: from, [USAGE_RANGE_TO_PARAM]: to };
  }
  return { [USAGE_RANGE_PARAM]: key, [USAGE_RANGE_FROM_PARAM]: "", [USAGE_RANGE_TO_PARAM]: "" };
}

/** 两个日历日之间跨越的天数(含端点)。 */
export function calendarDayCount(from: string, to: string): number {
  const start = new Date(`${from}T00:00:00`);
  const end = new Date(`${to}T00:00:00`);
  return Math.round((end.getTime() - start.getTime()) / 86_400_000) + 1;
}

/** 区间跨越的日历日数(含端点)。 */
export function usageRangeDayCount(range: UsageRange): number {
  return calendarDayCount(range.from, range.to);
}
