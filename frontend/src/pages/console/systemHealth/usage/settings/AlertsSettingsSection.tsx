import { Badge } from "../../../../../components/Badge";
import { Field, TextInput } from "../../../../../components/Field";
import { useI18n } from "../../../../../i18n/I18nProvider";
import { SettingsSubBlock, SettingsToggle } from "../../../SettingsCard";
import { USAGE_RANGES } from "./usageSettingsDocument";
import { fieldErrorText, type UsageAlertsFormState, type UsageFieldErrors } from "./usageSettingsForm";
import { UsageNumberField } from "./UsageNumberField";

/** 概览里只读的发送方可用性与接收人规模, 帮助确认告警真的送得出去。 */
export interface AlertsReadiness {
  senderReady: boolean;
  senderProblem: string | null;
  recipientCount: number;
}

export function AlertsSettingsSection({
  form,
  errors,
  readiness,
  onChange,
}: {
  form: UsageAlertsFormState;
  errors: UsageFieldErrors;
  readiness: AlertsReadiness | null;
  onChange: (updater: (current: UsageAlertsFormState) => UsageAlertsFormState) => void;
}) {
  const { t } = useI18n();

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h3 className="text-base font-semibold leading-tight text-ink">{t("usageSettings.alerts.title")}</h3>
        <p className="text-body leading-5 text-ink-soft">{t("usageSettings.alerts.description")}</p>
      </header>
      <SettingsToggle
        label={t("usageSettings.alerts.enabled")}
        hint={t("usageSettings.alerts.enabledHint")}
        checked={form.enabled}
        onChange={(enabled) => onChange((current) => ({ ...current, enabled }))}
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <UsageNumberField
          label={t("usageSettings.alerts.cooldown")}
          hint={t("usageSettings.alerts.cooldownHint")}
          error={fieldErrorText(t, errors, "alerts.cooldown_minutes")}
          value={form.cooldownMinutes}
          min={USAGE_RANGES.cooldownMinutes.min}
          max={USAGE_RANGES.cooldownMinutes.max}
          onChange={(cooldownMinutes) => onChange((current) => ({ ...current, cooldownMinutes }))}
        />
        <UsageNumberField
          label={t("usageSettings.alerts.dailyCap")}
          hint={t("usageSettings.alerts.dailyCapHint")}
          error={fieldErrorText(t, errors, "alerts.daily_cap")}
          value={form.dailyCap}
          min={USAGE_RANGES.alertsDailyCap.min}
          max={USAGE_RANGES.alertsDailyCap.max}
          onChange={(dailyCap) => onChange((current) => ({ ...current, dailyCap }))}
        />
      </div>
      <Field
        label={t("usageSettings.alerts.senderAppKey")}
        hint={t("usageSettings.alerts.senderAppKeyHint")}
        error={fieldErrorText(t, errors, "alerts.sender_app_key")}
      >
        <TextInput
          autoComplete="off"
          className="font-mono"
          value={form.senderAppKey}
          onChange={(event) => {
            const senderAppKey = event.currentTarget.value;
            onChange((current) => ({ ...current, senderAppKey }));
          }}
        />
      </Field>
      <SettingsSubBlock title={t("usageSettings.alerts.readiness")} hint={t("usageSettings.alerts.recipientsHint")}>
        <AlertsReadinessRow readiness={readiness} />
      </SettingsSubBlock>
    </div>
  );
}

function AlertsReadinessRow({ readiness }: { readiness: AlertsReadiness | null }) {
  const { t } = useI18n();
  if (readiness === null) {
    return <p className="text-caption leading-5 text-ink-faint">{t("usageSettings.alerts.summaryUnavailable")}</p>;
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={readiness.senderReady ? "evergreen" : "signal"}>
          {readiness.senderReady ? t("usageSettings.alerts.senderReady") : t("usageSettings.alerts.senderProblem")}
        </Badge>
        <Badge tone={readiness.recipientCount > 0 ? "neutral" : "amber"}>
          {t("usageSettings.alerts.recipients", { count: readiness.recipientCount })}
        </Badge>
      </div>
      {readiness.senderProblem ? <p className="text-caption leading-5 text-signal">{readiness.senderProblem}</p> : null}
      {readiness.recipientCount === 0 ? (
        <p className="text-caption leading-5 text-amber">{t("usageSettings.alerts.recipientsEmpty")}</p>
      ) : null}
    </div>
  );
}
