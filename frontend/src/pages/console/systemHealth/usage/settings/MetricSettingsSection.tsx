import { StatusBanner } from "../../../../../components/StatusBanner";
import { useI18n } from "../../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../../i18n/messages";
import type { UsageMetricKey, UsageOverLimitPolicy } from "../usageTypes";
import { AnomalyFields } from "./AnomalyFields";
import { PolicyPicker } from "./PolicyPicker";
import { PriorityLegend } from "./PriorityLegend";
import { QuotaPreviewBar } from "./QuotaPreviewBar";
import { ThresholdChipsEditor } from "./ThresholdChipsEditor";
import { USAGE_RANGES } from "./usageSettingsDocument";
import { fieldErrorText, type UsageFieldErrors, type UsageMetricFormState } from "./usageSettingsForm";
import { UsageNumberField } from "./UsageNumberField";

/** 预览条需要的两个数字, 由弹窗从概览载荷里取出后传进来。 */
export interface MetricUsageSnapshot {
  today: number;
  month: number;
}

const TITLE_KEYS: Record<UsageMetricKey, MessageKey> = {
  api: "usageSettings.metric.api.title",
  webhook: "usageSettings.metric.webhook.title",
  stream: "usageSettings.metric.stream.title",
};

const DESCRIPTION_KEYS: Record<UsageMetricKey, MessageKey> = {
  api: "usageSettings.metric.api.description",
  webhook: "usageSettings.metric.webhook.description",
  stream: "usageSettings.metric.stream.description",
};

export function MetricSettingsSection({
  metric,
  form,
  errors,
  usage,
  onChange,
  onSelectPolicy,
}: {
  metric: UsageMetricKey;
  form: UsageMetricFormState;
  errors: UsageFieldErrors;
  usage: MetricUsageSnapshot | null;
  onChange: (updater: (current: UsageMetricFormState) => UsageMetricFormState) => void;
  onSelectPolicy: (policy: UsageOverLimitPolicy) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h3 className="text-base font-semibold leading-tight text-ink">{t(TITLE_KEYS[metric])}</h3>
        <p className="text-body leading-5 text-ink-soft">{t(DESCRIPTION_KEYS[metric])}</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        <UsageNumberField
          label={t("usageSettings.quota.monthly")}
          hint={t("usageSettings.quota.monthlyHint")}
          error={fieldErrorText(t, errors, `${metric}.monthly_quota`)}
          value={form.monthlyQuota}
          placeholder={t("usageSettings.quota.placeholder")}
          min={USAGE_RANGES.quota.min}
          max={USAGE_RANGES.quota.max}
          onChange={(monthlyQuota) => onChange((current) => ({ ...current, monthlyQuota }))}
        />
        <UsageNumberField
          label={t("usageSettings.quota.daily")}
          hint={t("usageSettings.quota.dailyHint")}
          error={fieldErrorText(t, errors, `${metric}.daily_cap`)}
          value={form.dailyCap}
          placeholder={t("usageSettings.quota.placeholder")}
          min={USAGE_RANGES.quota.min}
          max={USAGE_RANGES.quota.max}
          onChange={(dailyCap) => onChange((current) => ({ ...current, dailyCap }))}
        />
      </div>
      <QuotaPreview form={form} usage={usage} />
      <ThresholdChipsEditor
        thresholds={form.thresholds}
        error={fieldErrorText(t, errors, `${metric}.alert_thresholds_percent`)}
        onChange={(thresholds) => onChange((current) => ({ ...current, thresholds }))}
      />
      <PolicyPicker metric={metric} form={form} onSelect={onSelectPolicy} />
      <PolicyConditionalFields metric={metric} form={form} errors={errors} onChange={onChange} />
      <AnomalyFields
        metric={metric}
        form={form.anomaly}
        errors={errors}
        onChange={(updater) => onChange((current) => ({ ...current, anomaly: updater(current.anomaly) }))}
      />
      {metric === "api" ? <PriorityLegend /> : null}
    </div>
  );
}

function QuotaPreview({ form, usage }: { form: UsageMetricFormState; usage: MetricUsageSnapshot | null }) {
  const { t } = useI18n();

  return (
    <div className="space-y-3 rounded-[3px] border border-ink/12 bg-paper-deep/40 p-3">
      <p className="text-label font-semibold uppercase tracking-caps text-ink-faint">{t("usageSettings.preview.title")}</p>
      <QuotaPreviewBar
        label={t("usageSettings.preview.today")}
        used={usage?.today ?? null}
        limit={parseLimit(form.dailyCap)}
        thresholds={form.thresholds}
      />
      <QuotaPreviewBar
        label={t("usageSettings.preview.month")}
        used={usage?.month ?? null}
        limit={parseLimit(form.monthlyQuota)}
        thresholds={form.thresholds}
      />
      <p className="text-xs leading-5 text-ink-faint">{t("usageSettings.preview.caption")}</p>
    </div>
  );
}

/**
 * 只有被选中的策略才会显示自己的参数; 校验失败的字段即使策略已切走也要显示,
 * 否则错误会藏在看不见的输入框里。
 */
function PolicyConditionalFields({
  metric,
  form,
  errors,
  onChange,
}: {
  metric: UsageMetricKey;
  form: UsageMetricFormState;
  errors: UsageFieldErrors;
  onChange: (updater: (current: UsageMetricFormState) => UsageMetricFormState) => void;
}) {
  const { t } = useI18n();
  if (metric === "stream") {
    return form.policy === "pause_stream" ? (
      <StatusBanner
        tone="amber"
        title={t("usageSettings.policy.pauseStreamWarning.title")}
        message={t("usageSettings.policy.pauseStreamWarning.message")}
      />
    ) : null;
  }
  if (metric !== "api") {
    return null;
  }
  const escalationError = fieldErrorText(t, errors, "api.degrade_escalation_percent");
  const throttleP1Error = fieldErrorText(t, errors, "api.throttle_per_hour.p1");
  const throttleP2Error = fieldErrorText(t, errors, "api.throttle_per_hour.p2");
  const showDegrade = form.policy === "degrade" || escalationError !== undefined;
  const showThrottle = form.policy === "throttle" || throttleP1Error !== undefined || throttleP2Error !== undefined;

  if (!showDegrade && !showThrottle) {
    return null;
  }
  return (
    <div className="route-transition grid gap-4 sm:grid-cols-2">
      {showDegrade ? (
        <UsageNumberField
          label={t("usageSettings.degrade.escalation")}
          hint={t("usageSettings.degrade.escalationHint")}
          error={escalationError}
          value={form.degradeEscalationPercent}
          min={USAGE_RANGES.degradeEscalation.min}
          max={USAGE_RANGES.degradeEscalation.max}
          onChange={(degradeEscalationPercent) => onChange((current) => ({ ...current, degradeEscalationPercent }))}
        />
      ) : null}
      {showThrottle ? (
        <>
          <UsageNumberField
            label={t("usageSettings.throttle.p1")}
            hint={t("usageSettings.throttle.hint")}
            error={throttleP1Error}
            value={form.throttleP1}
            min={USAGE_RANGES.throttle.min}
            max={USAGE_RANGES.throttle.max}
            onChange={(throttleP1) => onChange((current) => ({ ...current, throttleP1 }))}
          />
          <UsageNumberField
            label={t("usageSettings.throttle.p2")}
            hint={t("usageSettings.throttle.hint")}
            error={throttleP2Error}
            value={form.throttleP2}
            min={USAGE_RANGES.throttle.min}
            max={USAGE_RANGES.throttle.max}
            onChange={(throttleP2) => onChange((current) => ({ ...current, throttleP2 }))}
          />
        </>
      ) : null}
    </div>
  );
}

function parseLimit(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) && value > 0 ? value : null;
}
