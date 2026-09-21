/**
 * 用量监控控制台 API 的前端类型(契约 §2 设置文档 + §4 接口载荷)。
 *
 * 本文件是 F2/F3 共用的唯一类型来源: 用量设置弹窗(F3)也从这里取类型,
 * 不要在各自的组件里再声明一份同形状的接口。
 */

export type UsageMetricKey = "api" | "webhook" | "stream";

/** 分类维度上还会出现 internal(内部调用), 它不计费也不受配额约束。 */
export type UsageCategoryMetric = UsageMetricKey | "internal";

export type UsageSource = "easyauth" | "authentik";

export type UsagePriority = "p0" | "p1" | "p2";

export type UsageEnforcementStateKey =
  | "normal"
  | "degraded_p2"
  | "degraded_p1"
  | "throttled"
  | "blocked"
  | "stream_paused";

export type UsageOverLimitPolicy = "alert_only" | "degrade" | "throttle" | "block_all" | "pause_stream";

export type UsageLimitReason = "daily_cap" | "monthly_quota";

export type UsageScope = "day" | "month";

/** 未配置上限时 cap/remaining/percent 全为 null, 前端据此渲染「未设置配额」。 */
export interface UsageTodayWindow {
  used: number;
  cap: number | null;
  remaining: number | null;
  percent: number | null;
}

export interface UsageMonthWindow {
  used: number;
  quota: number | null;
  remaining: number | null;
  percent: number | null;
  period_start: string;
  period_end: string;
  projected: number | null;
}

export interface UsageEnforcementSummary {
  state: UsageEnforcementStateKey;
  reason: UsageLimitReason | null;
  since: string | null;
}

export interface UsageNextThreshold {
  scope: UsageScope;
  percent: number;
  remaining: number;
}

export interface UsageMetricSummary {
  metric: UsageMetricKey;
  policy: UsageOverLimitPolicy;
  today: UsageTodayWindow;
  month: UsageMonthWindow;
  enforcement: UsageEnforcementSummary;
  thresholds_percent: number[];
  next_threshold: UsageNextThreshold | null;
  blocked_today: number;
  last_hour: number;
}

/** total = billed + unbilled + internal。 */
export interface UsageApiBreakdown {
  total: number;
  billed: number;
  unbilled: number;
  internal: number;
}

export interface UsageAlertsSummary {
  sent_today: number;
  suppressed_today: number;
  daily_cap: number;
  sender_ready: boolean;
  sender_problem: string | null;
  recipient_count: number;
}

export interface UsageStreamSummary {
  paused: boolean;
  paused_at: string | null;
  can_resume: boolean;
}

export interface UsageAuthentikSummary {
  pulled_at: string | null;
  stale: boolean;
  error: string | null;
}

export interface UsageSummaryPayload {
  generated_at: string;
  timezone: string;
  /** 顺序固定为 api / webhook / stream。 */
  metrics: UsageMetricSummary[];
  api_breakdown_today: UsageApiBreakdown;
  alerts: UsageAlertsSummary;
  stream: UsageStreamSummary;
  authentik: UsageAuthentikSummary;
}

export type UsageGranularity = "hour" | "day";

export interface UsageSeriesPoint {
  start: string;
  api_billed: number;
  api_unbilled: number;
  internal: number;
  webhook: number;
  stream: number;
  blocked: number;
}

export type UsageSeriesTotals = Omit<UsageSeriesPoint, "start">;

/**
 * 控制台是否按请求语言返回 `label` 由 H5 决定; 拿不到时回落 `label_zh` / `label_en`,
 * 因此三个字段都声明为可选, 读取统一走 usageCategoryLabel()。
 */
export interface UsageCategoryTotal {
  metric: UsageCategoryMetric;
  category: string;
  label?: string;
  label_zh?: string;
  label_en?: string;
  source: UsageSource;
  billed: boolean;
  priority: UsagePriority | null;
  count: number;
  blocked: number;
}

export interface UsageTimeseriesPayload {
  from: string;
  to: string;
  granularity: UsageGranularity;
  points: UsageSeriesPoint[];
  totals: UsageSeriesTotals;
  categories: UsageCategoryTotal[];
}

export type UsageAlertKind = "threshold" | "anomaly" | "enforcement" | "stream_paused" | "stream_resumed";

export type UsageAlertStatus = "sent" | "suppressed" | "superseded" | "failed";

export interface UsageAlertEvent {
  id: number;
  kind: UsageAlertKind;
  metric: string;
  scope: string;
  period_key: string;
  threshold_percent: number;
  status: UsageAlertStatus;
  title: string;
  detail: string;
  failure_reason: string;
  created_at: string;
}

export interface UsageAlertsPayload {
  data: UsageAlertEvent[];
}

/* ------------------------------------------------------------------ */
/* 设置文档(契约 §2) —— F3 的设置弹窗消费                              */
/* ------------------------------------------------------------------ */

export interface UsageAnomalyConfig {
  enabled: boolean;
  hourly_absolute: number | null;
  baseline_multiplier: number;
  baseline_min_calls: number;
}

export interface UsageThrottlePerHour {
  p1: number | null;
  p2: number | null;
}

export interface UsageApiMetricConfig {
  monthly_quota: number | null;
  daily_cap: number | null;
  alert_thresholds_percent: number[];
  over_limit_policy: Extract<UsageOverLimitPolicy, "alert_only" | "degrade" | "throttle" | "block_all">;
  degrade_escalation_percent: number;
  throttle_per_hour: UsageThrottlePerHour;
  anomaly: UsageAnomalyConfig;
}

export interface UsageWebhookMetricConfig {
  monthly_quota: number | null;
  daily_cap: number | null;
  alert_thresholds_percent: number[];
  over_limit_policy: Extract<UsageOverLimitPolicy, "alert_only">;
  anomaly: UsageAnomalyConfig;
}

export interface UsageStreamMetricConfig {
  monthly_quota: number | null;
  daily_cap: number | null;
  alert_thresholds_percent: number[];
  over_limit_policy: Extract<UsageOverLimitPolicy, "alert_only" | "pause_stream">;
  anomaly: UsageAnomalyConfig;
}

export interface UsageAlertsConfig {
  enabled: boolean;
  cooldown_minutes: number;
  daily_cap: number;
  sender_app_key: string;
}

export interface UsageConfig {
  api: UsageApiMetricConfig;
  webhook: UsageWebhookMetricConfig;
  stream: UsageStreamMetricConfig;
  alerts: UsageAlertsConfig;
}

export interface UsageSettingsPayload {
  config: UsageConfig;
  version: number;
  updated_at: string;
  updated_by: string;
}

/** 分类标签: 后端按请求语言给 `label` 时用它, 否则按当前语言回落中英字段。 */
export function usageCategoryLabel(row: UsageCategoryTotal, preferEnglish: boolean): string {
  if (preferEnglish) {
    return row.label_en || row.label || row.label_zh || row.category;
  }
  return row.label || row.label_zh || row.label_en || row.category;
}
