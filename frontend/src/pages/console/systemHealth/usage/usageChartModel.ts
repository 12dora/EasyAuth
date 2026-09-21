import type { MessageKey } from "../../../../i18n/messages";
import type { UsageGranularity, UsageSeriesPoint, UsageSeriesTotals } from "./usageTypes";

export type UsageSeriesKey = keyof UsageSeriesTotals;

/** 主图的堆叠顺序(自下而上), 同时也是图例顺序。 */
export const USAGE_STACK_SERIES = ["api_billed", "api_unbilled", "internal"] as const;

export type UsageStackSeriesKey = (typeof USAGE_STACK_SERIES)[number];

export const USAGE_ALL_SERIES: readonly UsageSeriesKey[] = [
  ...USAGE_STACK_SERIES,
  "webhook",
  "stream",
  "blocked",
];

export const USAGE_SERIES_LABEL_KEYS: Record<UsageSeriesKey, MessageKey> = {
  api_billed: "usage.series.api_billed",
  api_unbilled: "usage.series.api_unbilled",
  internal: "usage.series.internal",
  webhook: "usage.series.webhook",
  stream: "usage.series.stream",
  blocked: "usage.series.blocked",
};

export interface UsageChartRow extends UsageSeriesPoint {
  /** X 轴刻度文案: 小时粒度 HH:00, 天粒度 MM-DD。 */
  label: string;
  /** 悬浮卡标题: 小时粒度补上日期, 免得跨天时只剩一个孤零零的钟点。 */
  tooltipLabel: string;
}

/**
 * 桶起点 ISO 串里的字面日期与小时。
 *
 * 后端按 settings.TIME_ZONE 生成带偏移的时间戳, 这里直接读字符串的字段,
 * 不经过 Date 换算 —— 浏览器时区与服务端不同时, 换算会把「8 点那一桶」画到别的位置。
 */
const BUCKET_FIELDS = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})/;

export function formatBucketLabel(start: string, granularity: UsageGranularity): string {
  const fields = BUCKET_FIELDS.exec(start);
  if (!fields) {
    return start;
  }
  const [, , month, day, hour] = fields;
  return granularity === "hour" ? `${hour}:00` : `${month}-${day}`;
}

export function formatBucketTooltipLabel(start: string, granularity: UsageGranularity): string {
  const fields = BUCKET_FIELDS.exec(start);
  if (!fields) {
    return start;
  }
  const [, year, month, day, hour] = fields;
  return granularity === "hour" ? `${month}-${day} ${hour}:00` : `${year}-${month}-${day}`;
}

export function toUsageChartRows(
  points: readonly UsageSeriesPoint[],
  granularity: UsageGranularity,
): UsageChartRow[] {
  return points.map((point) => ({
    ...point,
    label: formatBucketLabel(point.start, granularity),
    tooltipLabel: formatBucketTooltipLabel(point.start, granularity),
  }));
}

/** 桶内除「被拒绝」以外的调用总数; 被拒绝的调用没有真正发出去, 不进合计。 */
export function bucketTotal(point: UsageSeriesPoint): number {
  return point.api_billed + point.api_unbilled + point.internal + point.webhook + point.stream;
}

export function hasAnyUsage(points: readonly UsageSeriesPoint[]): boolean {
  return points.some((point) => bucketTotal(point) > 0 || point.blocked > 0);
}

const axisFormatters = new Map<string, Intl.NumberFormat>();

/** 坐标轴刻度: 上万后压缩成 12K / 1.2M, 免得 Y 轴把绘图区挤窄。 */
export function formatAxisCount(value: number, locale: string): string {
  const compact = Math.abs(value) >= 10_000;
  const cacheKey = `${locale}:${compact}`;
  let formatter = axisFormatters.get(cacheKey);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, compact ? { notation: "compact", maximumFractionDigits: 1 } : {});
    axisFormatters.set(cacheKey, formatter);
  }
  return formatter.format(value);
}

/** `prefers-reduced-motion` 判定; 图表入场动画与数字滚动共用。 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
