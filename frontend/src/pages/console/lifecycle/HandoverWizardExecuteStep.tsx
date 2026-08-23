import { Badge } from "../../../components/Badge";
import { StatusBanner } from "../../../components/StatusBanner";
import { actionStatusBadgeTone, actionStatusLabel } from "../../../features/handover/handoverActionPanelModel";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverAction } from "../../../lib/domain";
import type { WizardExecuteState } from "./handoverWizardModel";
import { StepSection } from "./HandoverWizardChrome";

export interface HandoverWizardExecuteStepProps {
  selectedApps: HandoverAction[];
  localActions: Record<string, HandoverAction>;
  executeState: Record<string, WizardExecuteState>;
  blockedCount: number;
  allExecuted: boolean;
}

export function HandoverWizardExecuteStep({
  selectedApps,
  localActions,
  executeState,
  blockedCount,
  allExecuted,
}: HandoverWizardExecuteStepProps) {
  const { t } = useI18n();
  return (
    <StepSection hint={t("handover.wizard.execute.hint")}>
      {blockedCount > 0 ? (
        <StatusBanner
          live="status"
          tone="amber"
          title={t("handover.wizard.execute.blockedSummary", { count: blockedCount })}
        />
      ) : null}
      <ul className="grid gap-2">
        {selectedApps.map((base) => {
          const action = localActions[base.app_key] ?? base;
          return (
            <li key={action.app_key} className="rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-body">{action.app_name || action.app_key}</strong>
                <ExecuteStateBadge state={executeState[action.app_key]} action={action} />
              </div>
            </li>
          );
        })}
      </ul>
      {allExecuted ? <StatusBanner live="status" tone="evergreen" title={t("handover.wizard.execute.done")} /> : null}
    </StepSection>
  );
}

function ExecuteStateBadge({ state, action }: { state: WizardExecuteState | undefined; action: HandoverAction }) {
  const { t } = useI18n();
  if (state === "done") {
    return <Badge tone="evergreen">{t("handover.actionStatus.done")}</Badge>;
  }
  if (state === "failed") {
    return <Badge tone="signal">{t("handover.actionStatus.failed")}</Badge>;
  }
  if (state === "running") {
    return <Badge tone="amber">{t("handover.actionStatus.executing")}</Badge>;
  }
  if (state === "async_pending") {
    return <Badge tone="amber">{t("handover.actionStatus.asyncPending")}</Badge>;
  }
  return <Badge tone={actionStatusBadgeTone(action.status)}>{actionStatusLabel(t, action.status)}</Badge>;
}
