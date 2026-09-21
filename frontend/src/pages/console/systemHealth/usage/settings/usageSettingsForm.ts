import type { MessageKey } from "../../../../../i18n/messages";
import type { Translator } from "../../../../../lib/status";
import type {
  UsageAnomalyConfig,
  UsageApiMetricConfig,
  UsageConfig,
  UsageMetricKey,
  UsageOverLimitPolicy,
  UsageStreamMetricConfig,
  UsageWebhookMetricConfig,
} from "../usageTypes";
import { USAGE_RANGES, type UsageSettingsSection } from "./usageSettingsDocument";

/** 校验失败信息按字段路径收集; 路径与文档键一致(api.monthly_quota), 便于映射服务端 422 的 details.fields。 */
export interface UsageFieldError {
  key: MessageKey;
  vars?: Record<string, string | number>;
}
export type UsageFieldErrors = Record<string, UsageFieldError>;

export interface UsageAnomalyFormState {
  enabled: boolean;
  hourlyAbsolute: string;
  baselineMultiplier: string;
  baselineMinCalls: string;
}

/**
 * 三个指标共用一套表单结构: 数值一律以字符串暂存(空串=不限制),
 * 只有 api 会用到 degrade/throttle 三项, 其余指标保持空串并且不会写回文档。
 */
export interface UsageMetricFormState {
  monthlyQuota: string;
  dailyCap: string;
  thresholds: number[];
  policy: UsageOverLimitPolicy;
  degradeEscalationPercent: string;
  throttleP1: string;
  throttleP2: string;
  anomaly: UsageAnomalyFormState;
}

export interface UsageAlertsFormState {
  enabled: boolean;
  cooldownMinutes: string;
  dailyCap: string;
  senderAppKey: string;
}

export interface UsageSettingsFormState {
  api: UsageMetricFormState;
  webhook: UsageMetricFormState;
  stream: UsageMetricFormState;
  alerts: UsageAlertsFormState;
}

const METRICS: readonly UsageMetricKey[] = ["api", "webhook", "stream"];

export function documentToForm(config: UsageConfig): UsageSettingsFormState {
  return {
    api: {
      monthlyQuota: numberText(config.api.monthly_quota),
      dailyCap: numberText(config.api.daily_cap),
      thresholds: [...config.api.alert_thresholds_percent],
      policy: config.api.over_limit_policy,
      degradeEscalationPercent: numberText(config.api.degrade_escalation_percent),
      throttleP1: numberText(config.api.throttle_per_hour.p1),
      throttleP2: numberText(config.api.throttle_per_hour.p2),
      anomaly: anomalyToForm(config.api.anomaly),
    },
    webhook: inboundMetricToForm(config.webhook),
    stream: inboundMetricToForm(config.stream),
    alerts: {
      enabled: config.alerts.enabled,
      cooldownMinutes: numberText(config.alerts.cooldown_minutes),
      dailyCap: numberText(config.alerts.daily_cap),
      senderAppKey: config.alerts.sender_app_key,
    },
  };
}

/** 仅在 validateForm 通过后调用: 任何解析失败都是前端不变量破裂, 直接抛错而不是静默兜底。 */
export function formToDocument(form: UsageSettingsFormState): UsageConfig {
  return {
    api: apiFromForm(form.api),
    webhook: {
      monthly_quota: optionalNumber(form.webhook.monthlyQuota, "webhook.monthly_quota"),
      daily_cap: optionalNumber(form.webhook.dailyCap, "webhook.daily_cap"),
      alert_thresholds_percent: sortedThresholds(form.webhook.thresholds),
      over_limit_policy: "alert_only",
      anomaly: anomalyFromForm(form.webhook.anomaly, "webhook"),
    },
    stream: {
      monthly_quota: optionalNumber(form.stream.monthlyQuota, "stream.monthly_quota"),
      daily_cap: optionalNumber(form.stream.dailyCap, "stream.daily_cap"),
      alert_thresholds_percent: sortedThresholds(form.stream.thresholds),
      over_limit_policy: form.stream.policy === "pause_stream" ? "pause_stream" : "alert_only",
      anomaly: anomalyFromForm(form.stream.anomaly, "stream"),
    },
    alerts: {
      enabled: form.alerts.enabled,
      cooldown_minutes: requiredNumber(form.alerts.cooldownMinutes, "alerts.cooldown_minutes"),
      daily_cap: requiredNumber(form.alerts.dailyCap, "alerts.daily_cap"),
      sender_app_key: form.alerts.senderAppKey.trim(),
    },
  };
}

export function validateForm(form: UsageSettingsFormState): UsageFieldErrors {
  const errors: UsageFieldErrors = {};
  for (const metric of METRICS) {
    validateMetric(metric, form[metric], errors);
  }
  const { alerts } = form;
  assign(errors, "alerts.cooldown_minutes", integerError(alerts.cooldownMinutes, USAGE_RANGES.cooldownMinutes, true));
  assign(errors, "alerts.daily_cap", integerError(alerts.dailyCap, USAGE_RANGES.alertsDailyCap, true));
  if (alerts.senderAppKey.trim() === "") {
    errors["alerts.sender_app_key"] = { key: "usageSettings.error.required" };
  }
  return errors;
}

export function sectionOfField(path: string): UsageSettingsSection | null {
  const head = path.split(".")[0];
  return head === "api" || head === "webhook" || head === "stream" || head === "alerts" ? head : null;
}

/** 第一个出错字段所在分区, 用于提交失败时把用户带回出问题的那一屏。 */
export function firstErrorSection(errors: UsageFieldErrors): UsageSettingsSection | null {
  for (const path of Object.keys(errors)) {
    const section = sectionOfField(path);
    if (section) {
      return section;
    }
  }
  return null;
}

export function fieldErrorText(t: Translator, errors: UsageFieldErrors, path: string): string | undefined {
  const error = errors[path];
  return error ? t(error.key, error.vars) : undefined;
}

export function formsEqual(left: UsageSettingsFormState, right: UsageSettingsFormState): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function sortedThresholds(values: readonly number[]): number[] {
  return [...values].sort((left, right) => left - right);
}

function validateMetric(metric: UsageMetricKey, form: UsageMetricFormState, errors: UsageFieldErrors): void {
  assign(errors, `${metric}.monthly_quota`, integerError(form.monthlyQuota, USAGE_RANGES.quota, false));
  assign(errors, `${metric}.daily_cap`, integerError(form.dailyCap, USAGE_RANGES.quota, false));
  assign(errors, `${metric}.alert_thresholds_percent`, thresholdsError(form.thresholds));
  assign(errors, `${metric}.anomaly.hourly_absolute`, integerError(form.anomaly.hourlyAbsolute, USAGE_RANGES.hourlyAbsolute, false));
  assign(errors, `${metric}.anomaly.baseline_multiplier`, decimalError(form.anomaly.baselineMultiplier, USAGE_RANGES.baselineMultiplier));
  assign(errors, `${metric}.anomaly.baseline_min_calls`, integerError(form.anomaly.baselineMinCalls, USAGE_RANGES.baselineMinCalls, true));
  if (metric !== "api") {
    return;
  }
  assign(errors, "api.degrade_escalation_percent", integerError(form.degradeEscalationPercent, USAGE_RANGES.degradeEscalation, true));
  assign(errors, "api.throttle_per_hour.p1", integerError(form.throttleP1, USAGE_RANGES.throttle, true));
  assign(errors, "api.throttle_per_hour.p2", integerError(form.throttleP2, USAGE_RANGES.throttle, true));
}

function thresholdsError(values: readonly number[]): UsageFieldError | null {
  const { thresholdCount, threshold } = USAGE_RANGES;
  if (values.length < thresholdCount.min || values.length > thresholdCount.max) {
    return { key: "usageSettings.error.thresholdCount" };
  }
  const distinct = new Set(values);
  const invalid = values.some(
    (value) => !Number.isInteger(value) || value < threshold.min || value > threshold.max,
  );
  return invalid || distinct.size !== values.length ? { key: "usageSettings.error.thresholdRange" } : null;
}

function integerError(text: string, range: { min: number; max: number }, required: boolean): UsageFieldError | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return required ? { key: "usageSettings.error.required" } : null;
  }
  const value = Number(trimmed);
  if (!Number.isInteger(value) || value < range.min || value > range.max) {
    return { key: "usageSettings.error.integerRange", vars: { min: range.min, max: range.max } };
  }
  return null;
}

function decimalError(text: string, range: { min: number; max: number }): UsageFieldError | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return { key: "usageSettings.error.required" };
  }
  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < range.min || value > range.max) {
    return { key: "usageSettings.error.numberRange", vars: { min: range.min, max: range.max } };
  }
  return null;
}

function assign(errors: UsageFieldErrors, path: string, error: UsageFieldError | null): void {
  if (error) {
    errors[path] = error;
  }
}

function apiFromForm(form: UsageMetricFormState): UsageApiMetricConfig {
  return {
    monthly_quota: optionalNumber(form.monthlyQuota, "api.monthly_quota"),
    daily_cap: optionalNumber(form.dailyCap, "api.daily_cap"),
    alert_thresholds_percent: sortedThresholds(form.thresholds),
    over_limit_policy: form.policy === "pause_stream" ? "alert_only" : form.policy,
    degrade_escalation_percent: requiredNumber(form.degradeEscalationPercent, "api.degrade_escalation_percent"),
    throttle_per_hour: {
      p1: requiredNumber(form.throttleP1, "api.throttle_per_hour.p1"),
      p2: requiredNumber(form.throttleP2, "api.throttle_per_hour.p2"),
    },
    anomaly: anomalyFromForm(form.anomaly, "api"),
  };
}

function inboundMetricToForm(config: UsageWebhookMetricConfig | UsageStreamMetricConfig): UsageMetricFormState {
  return {
    monthlyQuota: numberText(config.monthly_quota),
    dailyCap: numberText(config.daily_cap),
    thresholds: [...config.alert_thresholds_percent],
    policy: config.over_limit_policy,
    degradeEscalationPercent: "",
    throttleP1: "",
    throttleP2: "",
    anomaly: anomalyToForm(config.anomaly),
  };
}

function anomalyToForm(anomaly: UsageAnomalyConfig): UsageAnomalyFormState {
  return {
    enabled: anomaly.enabled,
    hourlyAbsolute: numberText(anomaly.hourly_absolute),
    baselineMultiplier: numberText(anomaly.baseline_multiplier),
    baselineMinCalls: numberText(anomaly.baseline_min_calls),
  };
}

function anomalyFromForm(form: UsageAnomalyFormState, metric: string): UsageAnomalyConfig {
  return {
    enabled: form.enabled,
    hourly_absolute: optionalNumber(form.hourlyAbsolute, `${metric}.anomaly.hourly_absolute`),
    baseline_multiplier: requiredNumber(form.baselineMultiplier, `${metric}.anomaly.baseline_multiplier`),
    baseline_min_calls: requiredNumber(form.baselineMinCalls, `${metric}.anomaly.baseline_min_calls`),
  };
}

function numberText(value: number | null): string {
  return value === null ? "" : String(value);
}

function optionalNumber(text: string, field: string): number | null {
  return text.trim() === "" ? null : requiredNumber(text, field);
}

function requiredNumber(text: string, field: string): number {
  const value = Number(text.trim());
  if (text.trim() === "" || !Number.isFinite(value)) {
    throw new Error(`usage settings field "${field}" is not a number: ${JSON.stringify(text)}`);
  }
  return value;
}
