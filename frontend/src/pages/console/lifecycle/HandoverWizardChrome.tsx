import { Check } from "lucide-react";
import type { ReactNode } from "react";

import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";
import { HANDOVER_WIZARD_STEPS, type HandoverWizardStepId } from "./handoverWizardController";

export function WizardStepIndicator({ step, includeGrants }: { step: HandoverWizardStepId; includeGrants: boolean }) {
  const { t } = useI18n();
  const visibleSteps = includeGrants
    ? HANDOVER_WIZARD_STEPS
    : HANDOVER_WIZARD_STEPS.filter((item) => item.id !== "grants");
  const activeIndex = visibleSteps.findIndex((item) => item.id === step);
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 border-b border-ink/12 pb-4" aria-label={t("handover.wizard.stepsAria")}>
      {visibleSteps.map((item, index) => {
        const isActive = item.id === step;
        const isDone = activeIndex >= 0 && index < activeIndex;
        return (
          <li key={item.id} className="flex items-center gap-1" aria-current={isActive ? "step" : undefined}>
            {index > 0 ? <span aria-hidden="true" className="mx-1 hidden h-px w-5 bg-ink/15 sm:block" /> : null}
            <span className={cn("flex items-center gap-2 rounded-[3px] px-2 py-1 text-sm font-semibold", isActive ? "text-ink" : "text-ink-soft")}>
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
              {t(item.labelKey)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function StepSection({ hint, children }: { hint: string; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <p className="text-body leading-5 text-ink-soft">{hint}</p>
      {children}
    </section>
  );
}
