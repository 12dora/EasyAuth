/**
 * 设置弹窗的本地常量与派生类型。
 *
 * 文档本身的形状(契约 §2)由 F2 的 ../usageTypes 统一声明, 这里不再复制一份,
 * 只派生弹窗需要的策略子集, 并集中放置分区列表与取值区间。
 */
import type { UsageApiMetricConfig, UsageMetricKey, UsageStreamMetricConfig } from "../usageTypes";

export type ApiOverLimitPolicy = UsageApiMetricConfig["over_limit_policy"];
export type StreamOverLimitPolicy = UsageStreamMetricConfig["over_limit_policy"];

export type UsageSettingsSection = UsageMetricKey | "alerts";

export const USAGE_SECTIONS: readonly UsageSettingsSection[] = ["api", "webhook", "stream", "alerts"];

export const DEFAULT_ALERT_THRESHOLDS: readonly number[] = [50, 80, 100];

/** 契约 §2 的取值区间; 前端在提交前用同一套边界先行校验, 与后端 pydantic 一致。 */
export const USAGE_RANGES = {
  quota: { min: 1, max: 1_000_000_000 },
  threshold: { min: 1, max: 500 },
  thresholdCount: { min: 1, max: 5 },
  degradeEscalation: { min: 100, max: 1_000 },
  throttle: { min: 0, max: 100_000 },
  hourlyAbsolute: { min: 1, max: 1_000_000_000 },
  baselineMultiplier: { min: 1.5, max: 100 },
  baselineMinCalls: { min: 1, max: 1_000_000 },
  cooldownMinutes: { min: 5, max: 1_440 },
  alertsDailyCap: { min: 1, max: 200 },
} as const;
