import { useI18n } from "../../../../../i18n/I18nProvider";
import { SettingsSubBlock, SettingsToggle } from "../../../SettingsCard";
import type { UsageMetricKey } from "../usageTypes";
import { USAGE_RANGES } from "./usageSettingsDocument";
import { fieldErrorText, type UsageAnomalyFormState, type UsageFieldErrors } from "./usageSettingsForm";
import { UsageNumberField } from "./UsageNumberField";

/** 用量异常告警: 绝对阈值与基线倍数任意一条命中即告警, 与配额无关。 */
export function AnomalyFields({
  metric,
  form,
  errors,
  onChange,
}: {
  metric: UsageMetricKey;
  form: UsageAnomalyFormState;
  errors: UsageFieldErrors;
  onChange: (updater: (current: UsageAnomalyFormState) => UsageAnomalyFormState) => void;
}) {
  const { t } = useI18n();

  return (
    <SettingsSubBlock title={t("usageSettings.anomaly.title")} hint={t("usageSettings.anomaly.hint")}>
      <SettingsToggle
        label={t("usageSettings.anomaly.enabled")}
        hint={t("usageSettings.anomaly.enabledHint")}
        checked={form.enabled}
        onChange={(enabled) => onChange((current) => ({ ...current, enabled }))}
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <UsageNumberField
          label={t("usageSettings.anomaly.hourlyAbsolute")}
          hint={t("usageSettings.anomaly.hourlyAbsoluteHint")}
          error={fieldErrorText(t, errors, `${metric}.anomaly.hourly_absolute`)}
          value={form.hourlyAbsolute}
          placeholder={t("usageSettings.quota.placeholder")}
          min={USAGE_RANGES.hourlyAbsolute.min}
          max={USAGE_RANGES.hourlyAbsolute.max}
          onChange={(hourlyAbsolute) => onChange((current) => ({ ...current, hourlyAbsolute }))}
        />
        <UsageNumberField
          label={t("usageSettings.anomaly.baselineMultiplier")}
          hint={t("usageSettings.anomaly.baselineMultiplierHint")}
          error={fieldErrorText(t, errors, `${metric}.anomaly.baseline_multiplier`)}
          value={form.baselineMultiplier}
          min={USAGE_RANGES.baselineMultiplier.min}
          max={USAGE_RANGES.baselineMultiplier.max}
          step="any"
          onChange={(baselineMultiplier) => onChange((current) => ({ ...current, baselineMultiplier }))}
        />
        <UsageNumberField
          label={t("usageSettings.anomaly.baselineMinCalls")}
          hint={t("usageSettings.anomaly.baselineMinCallsHint")}
          error={fieldErrorText(t, errors, `${metric}.anomaly.baseline_min_calls`)}
          value={form.baselineMinCalls}
          min={USAGE_RANGES.baselineMinCalls.min}
          max={USAGE_RANGES.baselineMinCalls.max}
          onChange={(baselineMinCalls) => onChange((current) => ({ ...current, baselineMinCalls }))}
        />
      </div>
    </SettingsSubBlock>
  );
}
