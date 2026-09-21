import { Badge } from "../../../../../components/Badge";
import { useI18n } from "../../../../../i18n/I18nProvider";
import { cn } from "../../../../../lib/cn";
import type { BadgeTone } from "../../../../../lib/status";
import { policyEffectLines, policyOptions, type PolicyEffectLine, type PolicyOption } from "./policyOptions";
import type { UsageMetricKey, UsageOverLimitPolicy } from "../usageTypes";
import type { UsageMetricFormState } from "./usageSettingsForm";

const PRIORITY_TONES: readonly BadgeTone[] = ["bond", "neutral", "faint"];

/** 超限策略选择器: 可选卡片 + 当前策略对各优先级的实际后果。 */
export function PolicyPicker({
  metric,
  form,
  onSelect,
}: {
  metric: UsageMetricKey;
  form: UsageMetricFormState;
  onSelect: (policy: UsageOverLimitPolicy) => void;
}) {
  const { t } = useI18n();
  const options = policyOptions(metric);

  return (
    <fieldset>
      <legend className="mb-2 text-label font-medium uppercase tracking-caps-wide text-ink-soft">
        {t("usageSettings.policy.label")}
      </legend>
      <div className="flex flex-col gap-2">
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map((option) => (
            <PolicyCard
              key={option.value}
              metric={metric}
              option={option}
              selected={option.value === form.policy}
              onSelect={onSelect}
            />
          ))}
        </div>
        <p className="text-xs leading-5 text-ink-faint">
          {metric === "webhook" ? t("usageSettings.policy.webhook.locked") : t("usageSettings.policy.hint")}
        </p>
        <PolicyEffects metric={metric} lines={policyEffectLines(metric, form.policy, form)} policy={form.policy} />
      </div>
    </fieldset>
  );
}

function PolicyCard({
  metric,
  option,
  selected,
  onSelect,
}: {
  metric: UsageMetricKey;
  option: PolicyOption;
  selected: boolean;
  onSelect: (policy: UsageOverLimitPolicy) => void;
}) {
  const { t } = useI18n();
  const Icon = option.icon;

  return (
    <label
      className={cn(
        "flex gap-3 rounded-[3px] border p-3 transition-colors duration-150 motion-reduce:transition-none",
        "focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent/50",
        selected ? "border-accent bg-accent/[0.06]" : "border-ink/15 bg-paper-soft hover:border-ink/35",
        option.locked ? "cursor-not-allowed opacity-75" : "cursor-pointer",
      )}
    >
      <input
        type="radio"
        className="sr-only"
        name={`usage-policy-${metric}`}
        value={option.value}
        checked={selected}
        disabled={option.locked}
        onChange={() => onSelect(option.value)}
      />
      <Icon size={16} aria-hidden="true" className={cn("mt-0.5 shrink-0", selected ? "text-accent" : "text-ink-faint")} />
      <span className="min-w-0">
        <span className="block text-sm font-semibold leading-5 text-ink">{t(option.titleKey)}</span>
        <span className="mt-0.5 block text-xs leading-5 text-ink-soft">{t(option.descriptionKey)}</span>
      </span>
    </label>
  );
}

function PolicyEffects({
  lines,
  metric,
  policy,
}: {
  lines: PolicyEffectLine[];
  metric: UsageMetricKey;
  policy: UsageOverLimitPolicy;
}) {
  const { t } = useI18n();

  return (
    <div key={policy} className="route-transition rounded-[3px] border border-ink/12 bg-paper-deep/50 p-3">
      <p className="text-label font-semibold uppercase tracking-caps text-ink-faint">{t("usageSettings.policy.effectTitle")}</p>
      <ul className="mt-2 space-y-1.5">
        {lines.map((line, index) => (
          <li key={line.priorityKey ?? line.textKey} className="flex items-start gap-2 text-caption leading-5 text-ink-soft">
            {line.priorityKey ? <Badge tone={PRIORITY_TONES[index] ?? "neutral"}>{t(line.priorityKey)}</Badge> : null}
            <span className="min-w-0">{t(line.textKey, line.vars)}</span>
          </li>
        ))}
      </ul>
      {metric === "api" ? (
        <p className="mt-2 text-xs leading-5 text-ink-faint">{t("usageSettings.effect.api.unbilled")}</p>
      ) : null}
    </div>
  );
}
