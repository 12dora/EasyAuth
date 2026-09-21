import type { BadgeTone } from "../../../../lib/status";
import type { UsageSeverity } from "./usageChartTheme";
import type { UsageEnforcementStateKey } from "./usageTypes";

/** 严重度分档: 正常 → 留意(>= 50%) → 告警(>= 80%) → 超限(>= 100%)。 */
export const USAGE_ATTENTION_PERCENT = 50;
export const USAGE_WARNING_PERCENT = 80;
export const USAGE_CRITICAL_PERCENT = 100;

export function usageSeverity(percent: number | null | undefined): UsageSeverity {
  if (percent === null || percent === undefined) {
    return "normal";
  }
  if (percent >= USAGE_CRITICAL_PERCENT) {
    return "critical";
  }
  if (percent >= USAGE_WARNING_PERCENT) {
    return "warning";
  }
  if (percent >= USAGE_ATTENTION_PERCENT) {
    return "attention";
  }
  return "normal";
}

export interface UsageMeterGeometry {
  /** 轨道内已用部分的宽度百分比(0-100)。 */
  fillPercent: number;
  /** 超出 100% 的百分点, 不封顶 —— 超了多少必须如实说。 */
  overflowPercent: number;
  hasOverflow: boolean;
}

export function usageMeterGeometry(percent: number | null | undefined): UsageMeterGeometry {
  if (percent === null || percent === undefined || !Number.isFinite(percent) || percent <= 0) {
    return { fillPercent: 0, overflowPercent: 0, hasOverflow: false };
  }
  if (percent <= USAGE_CRITICAL_PERCENT) {
    return { fillPercent: percent, overflowPercent: 0, hasOverflow: false };
  }
  return { fillPercent: 100, overflowPercent: percent - USAGE_CRITICAL_PERCENT, hasOverflow: true };
}

/**
 * 轨道上的告警刻度位置。
 *
 * 只画落在轨道内的刻度(0 < p <= 100); 配置允许把阈值设到 500%, 那种刻度没有位置可放,
 * 它的存在由「下一档告警」文案与设置弹窗负责表达, 这里不做假的压缩。
 */
export function usageThresholdTicks(thresholds: readonly number[] | null | undefined): number[] {
  if (!thresholds) {
    return [];
  }
  const inTrack = thresholds.filter((value) => Number.isFinite(value) && value > 0 && value <= 100);
  return [...new Set(inTrack)].sort((left, right) => left - right);
}

/** 配额未配置时整张卡片走空态, 这里统一判定。 */
export function hasUsageLimit(limit: number | null | undefined): limit is number {
  return typeof limit === "number" && limit > 0;
}

const ENFORCEMENT_TONES: Record<UsageEnforcementStateKey, BadgeTone> = {
  normal: "evergreen",
  degraded_p2: "amber",
  degraded_p1: "amber",
  throttled: "amber",
  blocked: "signal",
  stream_paused: "signal",
};

export function enforcementTone(state: UsageEnforcementStateKey): BadgeTone {
  return ENFORCEMENT_TONES[state] ?? "neutral";
}

export function isEnforcementActive(state: UsageEnforcementStateKey): boolean {
  return state !== "normal";
}

const numberFormatters = new Map<string, Intl.NumberFormat>();

/** 千分位整数; 与 I18nProvider 一样按 locale 复用 Intl 实例。 */
export function formatUsageCount(value: number, locale: string): string {
  let formatter = numberFormatters.get(locale);
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
    numberFormatters.set(locale, formatter);
  }
  return formatter.format(value);
}

/** 百分比文案: 小于 10% 保留一位小数, 更大时取整, 避免大数字后面拖一位无意义的小数。 */
export function formatUsagePercent(percent: number): string {
  const rounded = percent < 10 ? Math.round(percent * 10) / 10 : Math.round(percent);
  return `${rounded}%`;
}

/** 占比条(分类表 / 构成条)用的宽度百分比。 */
export function sharePercent(value: number, total: number): number {
  if (total <= 0) {
    return 0;
  }
  return Math.min(100, (value / total) * 100);
}
