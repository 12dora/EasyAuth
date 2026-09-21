import { RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../../components/Button";
import { Field, TextInput } from "../../../../../components/Field";
import { useI18n } from "../../../../../i18n/I18nProvider";
import { DEFAULT_ALERT_THRESHOLDS, USAGE_RANGES } from "./usageSettingsDocument";
import { sortedThresholds } from "./usageSettingsForm";

/** 告警阈值编辑器: 芯片增删 + 排序, 取值与数量的边界在按钮可用性上就拦住。 */
export function ThresholdChipsEditor({
  thresholds,
  error,
  onChange,
}: {
  thresholds: number[];
  error?: string;
  onChange: (next: number[]) => void;
}) {
  const { t } = useI18n();
  const [draft, setDraft] = useState("");
  const parsed = Number(draft.trim());
  const full = thresholds.length >= USAGE_RANGES.thresholdCount.max;
  const canAdd =
    draft.trim() !== "" &&
    Number.isInteger(parsed) &&
    parsed >= USAGE_RANGES.threshold.min &&
    parsed <= USAGE_RANGES.threshold.max &&
    !thresholds.includes(parsed) &&
    !full;

  const add = () => {
    if (!canAdd) {
      return;
    }
    onChange(sortedThresholds([...thresholds, parsed]));
    setDraft("");
  };

  return (
    <Field as="group" label={t("usageSettings.thresholds.label")} hint={t("usageSettings.thresholds.hint")} error={error}>
      <div className="flex flex-wrap items-center gap-2">
        {sortedThresholds(thresholds).map((value) => (
          <span
            key={value}
            className="inline-flex items-center gap-1 rounded-full border border-ink/15 bg-paper-soft py-0.5 pl-2.5 pr-1 font-mono text-caption tabular-nums text-ink"
          >
            {t("usageSettings.thresholds.value", { percent: value })}
            <button
              type="button"
              aria-label={t("usageSettings.thresholds.remove", { percent: value })}
              className="inline-flex size-5 items-center justify-center rounded-full text-ink-faint transition-colors hover:bg-ink/8 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
              disabled={thresholds.length <= USAGE_RANGES.thresholdCount.min}
              onClick={() => onChange(thresholds.filter((item) => item !== value))}
            >
              <X size={12} aria-hidden="true" />
            </button>
          </span>
        ))}
        <div className="flex items-center gap-1.5">
          <TextInput
            aria-label={t("usageSettings.thresholds.addLabel")}
            className="w-24"
            inputMode="numeric"
            max={USAGE_RANGES.threshold.max}
            min={USAGE_RANGES.threshold.min}
            placeholder={t("usageSettings.thresholds.addPlaceholder")}
            type="number"
            value={draft}
            onChange={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
          />
          <Button type="button" disabled={!canAdd} onClick={add}>
            {t("usageSettings.thresholds.add")}
          </Button>
        </div>
        <Button
          type="button"
          variant="ghost"
          icon={<RotateCcw size={13} />}
          onClick={() => onChange([...DEFAULT_ALERT_THRESHOLDS])}
        >
          {t("usageSettings.thresholds.reset")}
        </Button>
      </div>
      {full ? <p className="mt-1.5 text-xs leading-5 text-ink-faint">{t("usageSettings.thresholds.full")}</p> : null}
    </Field>
  );
}
