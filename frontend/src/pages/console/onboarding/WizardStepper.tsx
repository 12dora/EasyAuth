import { Check } from "lucide-react";

import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";
import type { WizardStep } from "./types";
import { WIZARD_STEPS, isStepReachable } from "./wizardSteps";

export function WizardStepper({
  activeStepIndex,
  appKey,
  navigationLocked,
  doneBlocked,
  onNavigate,
}: {
  activeStepIndex: number;
  appKey: string;
  navigationLocked: boolean;
  doneBlocked: boolean;
  onNavigate: (step: WizardStep) => void;
}) {
  const { t } = useI18n();

  return (
    <ol className="mb-6 flex flex-wrap gap-x-1 gap-y-2 border-b border-ink/12 pb-4" aria-label={t("wizard.stepsAria")}>
      {WIZARD_STEPS.map((step, index) => {
        const isActive = index === activeStepIndex;
        const isDone = index < activeStepIndex;
        const isReachable = isStepReachable(step.key, index, { appKey, navigationLocked, doneBlocked });
        const stateLabel = isActive
          ? t("wizard.stepState.current")
          : isDone
            ? t("wizard.stepState.done")
            : t("wizard.stepState.pending");

        return (
          <li key={step.key} className="flex items-center gap-1">
            {index > 0 ? <span aria-hidden="true" className="mx-1 hidden h-px w-6 bg-ink/15 sm:block" /> : null}
            <button
              type="button"
              disabled={!isReachable}
              aria-current={isActive ? "step" : undefined}
              aria-label={`${t(step.labelKey)} - ${stateLabel}`}
              className={cn(
                "flex items-center gap-2 rounded-[3px] px-2 py-1 text-sm font-semibold transition-colors",
                isActive ? "text-ink" : "text-ink-soft",
                isReachable ? "hover:text-ink" : "cursor-not-allowed opacity-50",
              )}
              onClick={() => onNavigate(step.key)}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  isActive && "border-accent bg-accent text-paper",
                  isDone && "border-evergreen bg-evergreen/10 text-evergreen",
                  !isActive && !isDone && "border-ink/20 text-ink-soft",
                )}
              >
                {isDone ? <Check size={13} /> : index + 1}
              </span>
              {t(step.labelKey)}
            </button>
          </li>
        );
      })}
    </ol>
  );
}
