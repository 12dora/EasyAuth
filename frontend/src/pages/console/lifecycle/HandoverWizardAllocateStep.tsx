import { Button } from "../../../components/Button";
import { AssetAllocator } from "../../../features/handover/AssetAllocator";
import { HandoverUserPicker } from "../../../features/handover/HandoverUserPicker";
import { useI18n } from "../../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { HandoverAction, HandoverTaskDetail, HandoverUserRef } from "../../../lib/domain";
import { StepSection } from "./HandoverWizardChrome";

export interface HandoverWizardAllocateStepProps {
  task: HandoverTaskDetail;
  selectedApps: HandoverAction[];
  localActions: Record<string, HandoverAction>;
  onPreview: (appKey: string) => void;
  onGrantReceiverChange: (action: HandoverAction, user: HandoverUserRef | null) => Promise<void>;
  onAllocatorPatch: (
    action: HandoverAction,
    patch: { asset_types?: HandoverAction["asset_types"]; confirm_version?: number; overrides_version?: number },
  ) => void;
}

export function HandoverWizardAllocateStep({
  task,
  selectedApps,
  localActions,
  onPreview,
  onGrantReceiverChange,
  onAllocatorPatch,
}: HandoverWizardAllocateStepProps) {
  const { t } = useI18n();
  return (
    <StepSection hint={t("handover.wizard.allocate.hint")}>
      <ul className="grid gap-4">
        {selectedApps.map((base) => {
          const action = localActions[base.app_key] ?? base;
          return (
            <li key={action.app_key} className="space-y-2 rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-3">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-body text-ink">
                  {formatAppDisplayName({ name: action.app_name, alias: action.app_alias })}
                </strong>
                <Button size="sm" type="button" onClick={() => onPreview(action.app_key)}>
                  {action.status !== "previewed"
                    ? t("handover.portal.detail.preview")
                    : t("handover.portal.detail.repreview")}
                </Button>
              </div>
              {task.kind === "offboard" && action.status === "previewed" ? (
                <div>
                  <p className="mb-1 text-caption text-ink-faint">{t("handover.wizard.grantReceiver")}</p>
                  <HandoverUserPicker
                    surface="console"
                    taskId={task.id}
                    value={action.grant_receiver}
                    onChange={(user) => onGrantReceiverChange(action, user)}
                  />
                  <p className="mt-1 text-caption text-ink-faint">{t("handover.wizard.grantReceiverHint")}</p>
                </div>
              ) : null}
              {action.status === "previewed" ? (
                <AssetAllocator
                  surface="console"
                  taskId={task.id}
                  action={action}
                  onActionUpdated={(patch) => onAllocatorPatch(action, patch)}
                />
              ) : (
                <p className="text-body text-ink-faint">{t("handover.wizard.preview.loading")}</p>
              )}
            </li>
          );
        })}
      </ul>
    </StepSection>
  );
}
