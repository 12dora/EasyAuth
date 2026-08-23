import { Badge } from "../../../components/Badge";
import { useI18n } from "../../../i18n/I18nProvider";
import { cn } from "../../../lib/cn";
import type { HandoverAction } from "../../../lib/domain";
import { canSelectActionForWizard } from "./handoverWizardController";
import { StepSection } from "./HandoverWizardChrome";
import { handoverActionStatusLabel, handoverActionStatusTone } from "./lifecycleLabels";

export interface HandoverWizardAppsStepProps {
  batchActions: HandoverAction[];
  selected: Record<string, boolean>;
  selectedCount: number;
  onToggle: (appKey: string, checked: boolean) => void;
}

export function HandoverWizardAppsStep({
  batchActions,
  selected,
  selectedCount,
  onToggle,
}: HandoverWizardAppsStepProps) {
  const { t } = useI18n();
  return (
    <StepSection hint={t("handover.wizard.apps.hint")}>
      {batchActions.length === 0 ? (
        <p className="text-body text-ink-soft">{t("handover.wizard.apps.empty")}</p>
      ) : (
        <ul className="grid gap-2">
          {batchActions.map((action) => {
            const blocked = !canSelectActionForWizard(action);
            return (
              <li key={action.app_key}>
                <label
                  className={cn(
                    "flex items-center gap-2.5 rounded-[3px] border px-3 py-2.5 text-body",
                    blocked ? "border-signal/40 bg-signal/5 text-signal" : "border-ink/12 bg-paper-soft text-ink",
                  )}
                >
                  <input
                    type="checkbox"
                    disabled={blocked}
                    checked={Boolean(selected[action.app_key]) && !blocked}
                    onChange={(event) => onToggle(action.app_key, event.currentTarget.checked)}
                  />
                  <span className="flex-1 font-medium">{action.app_name || action.app_key}</span>
                  {blocked ? (
                    <span className="text-caption">{t("handover.wizard.apps.blocked")}</span>
                  ) : (
                    <Badge tone={handoverActionStatusTone(action.status)}>
                      {handoverActionStatusLabel(t, action.status)}
                    </Badge>
                  )}
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-caption text-ink-faint">{t("handover.wizard.apps.selectedCount", { count: selectedCount })}</p>
    </StepSection>
  );
}
