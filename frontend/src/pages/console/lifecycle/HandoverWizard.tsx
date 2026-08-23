import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverTaskDetail } from "../../../lib/domain";
import { useHandoverWizardController } from "./handoverWizardController";
import {
  initialWizardSelection,
  wizardBatchActions,
  wizardBlockedCount,
  wizardNextDisabled,
  wizardSelectedApps,
  wizardStepBack,
} from "./handoverWizardModel";
import { HandoverWizardAllocateStep } from "./HandoverWizardAllocateStep";
import { HandoverWizardAppsStep } from "./HandoverWizardAppsStep";
import { WizardStepIndicator } from "./HandoverWizardChrome";
import { HandoverWizardExecuteStep } from "./HandoverWizardExecuteStep";
import { HandoverWizardGrantsStep } from "./HandoverWizardGrantsStep";
import { useHandoverWizardExecution } from "./useHandoverWizardExecution";
import { useHandoverWizardGrants } from "./useHandoverWizardGrants";

interface HandoverWizardProps {
  task: HandoverTaskDetail;
  onClose: () => void;
}

/** 四段交接向导: 应用 → 授权 → 预演与分配 → 执行。接收人下沉到资产条目级。 */
export function HandoverWizard({ task, onClose }: HandoverWizardProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const detailQueryKey = useMemo(() => ["console", "handover-task", String(task.id)], [task.id]);

  const [batchActions] = useState(() => wizardBatchActions(task));
  const [selected, setSelected] = useState<Record<string, boolean>>(() => initialWizardSelection(batchActions));

  const wizard = useHandoverWizardController();
  const step = wizard.step;

  const selectedApps = useMemo(() => wizardSelectedApps(batchActions, selected), [batchActions, selected]);
  const blockedCount = wizardBlockedCount(batchActions);

  const invalidateDetail = useCallback(
    () => void queryClient.invalidateQueries({ queryKey: detailQueryKey }),
    [detailQueryKey, queryClient],
  );

  const grants = useHandoverWizardGrants(task, selectedApps);
  const run = useHandoverWizardExecution({ task, step, selectedApps, invalidateDetail });

  const includeGrantsStep = task.kind === "offboard";

  const goNext = () => {
    if (step === "apps") {
      if (selectedApps.length === 0) {
        return;
      }
      wizard.goTo(includeGrantsStep ? "grants" : "allocate");
      return;
    }
    if (step === "grants") {
      grants.saveGrantsMutation.mutate(undefined, { onSuccess: () => wizard.goTo("allocate") });
      return;
    }
    if (step === "allocate" && !run.allPreviewed) {
      return;
    }
    wizard.goNext();
  };

  const goBack = () => {
    const target = wizardStepBack(step, includeGrantsStep);
    if (target) {
      wizard.goTo(target);
      return;
    }
    wizard.goBack();
  };

  const isSaving = grants.saveGrantsMutation.isPending;

  return (
    <Dialog
      title={t("handover.wizard.title")}
      size="xl"
      onClose={() => !run.isExecuting && onClose()}
      closeDisabled={run.isExecuting}
    >
      <div className="space-y-5">
        <WizardStepIndicator step={step} includeGrants={includeGrantsStep} />
        {run.error ? <StatusBanner live="alert" tone="signal" title={run.error} /> : null}

        {step === "apps" ? (
          <HandoverWizardAppsStep
            batchActions={batchActions}
            selected={selected}
            selectedCount={selectedApps.length}
            onToggle={(appKey, checked) => setSelected((current) => ({ ...current, [appKey]: checked }))}
          />
        ) : null}

        {step === "grants" ? (
          <HandoverWizardGrantsStep
            apps={selectedApps}
            items={grants.grantItems}
            selection={grants.grantSelection}
            isLoading={grants.isLoading}
            error={grants.error}
            onToggle={grants.toggleGrant}
          />
        ) : null}

        {step === "allocate" ? (
          <HandoverWizardAllocateStep
            task={task}
            selectedApps={selectedApps}
            localActions={run.localActions}
            onPreview={(appKey) => void run.runPreview(appKey)}
            onGrantReceiverChange={run.setGrantReceiver}
            onAllocatorPatch={run.applyAllocatorPatch}
          />
        ) : null}

        {step === "execute" ? (
          <HandoverWizardExecuteStep
            selectedApps={selectedApps}
            localActions={run.localActions}
            executeState={run.executeState}
            blockedCount={blockedCount}
            allExecuted={run.allExecuted}
          />
        ) : null}

        <WizardFooter
          isFirstStep={wizard.isFirstStep}
          isLastStep={wizard.isLastStep}
          isSaving={isSaving}
          isExecuting={run.isExecuting}
          allExecuted={run.allExecuted}
          nextDisabled={wizardNextDisabled({
            step,
            selectedCount: selectedApps.length,
            grantsLoading: grants.isLoading,
            grantsFailed: Boolean(grants.error),
            allPreviewed: run.allPreviewed,
            isSaving,
            isExecuting: run.isExecuting,
          })}
          executeDisabled={run.isExecuting || selectedApps.length === 0 || !run.allPreviewed}
          onClose={onClose}
          onBack={goBack}
          onNext={goNext}
          onExecute={() => void run.runExecute()}
        />
      </div>
    </Dialog>
  );
}

interface WizardFooterProps {
  isFirstStep: boolean;
  isLastStep: boolean;
  isSaving: boolean;
  isExecuting: boolean;
  allExecuted: boolean;
  nextDisabled: boolean;
  executeDisabled: boolean;
  onClose: () => void;
  onBack: () => void;
  onNext: () => void;
  onExecute: () => void;
}

function WizardFooter({
  isFirstStep,
  isLastStep,
  isSaving,
  isExecuting,
  allExecuted,
  nextDisabled,
  executeDisabled,
  onClose,
  onBack,
  onNext,
  onExecute,
}: WizardFooterProps) {
  const { t } = useI18n();
  return (
    <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-ink/10 pt-4">
      <Button type="button" variant="ghost" disabled={isSaving || isExecuting} onClick={onClose}>
        {t("handover.wizard.saveLater")}
      </Button>
      <div className="flex flex-wrap gap-2">
        {!isFirstStep ? (
          <Button type="button" disabled={isSaving || isExecuting} onClick={onBack}>
            {t("common.back")}
          </Button>
        ) : null}
        {!isLastStep ? (
          <Button type="button" variant="primary" loading={isSaving} disabled={nextDisabled} onClick={onNext}>
            {t("common.next")}
          </Button>
        ) : allExecuted ? (
          <Button type="button" variant="primary" onClick={onClose}>
            {t("common.done")}
          </Button>
        ) : (
          <Button type="button" variant="primary" loading={isExecuting} disabled={executeDisabled} onClick={onExecute}>
            {t("handover.wizard.execute.run")}
          </Button>
        )}
      </div>
    </footer>
  );
}
