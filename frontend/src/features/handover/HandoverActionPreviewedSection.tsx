import { Button } from "../../components/Button";
import { useI18n } from "../../i18n/I18nProvider";
import type { HandoverAction, HandoverTaskDetail } from "../../lib/domain";
import type { ActionSnapshotScope } from "./actionSnapshotCache";
import { AssetAllocator } from "./AssetAllocator";
import { HandoverUserPicker } from "./HandoverUserPicker";

export interface HandoverActionPreviewedSectionProps {
  scope: ActionSnapshotScope;
  task: HandoverTaskDetail;
  action: HandoverAction;
  readOnly: boolean;
  grantBusy: boolean;
  actionMutationLock: boolean;
  allocatorResetKey: number;
  previewPending: boolean;
  onPreview: () => void;
  onGrantReceiverChange: (userId: string | null) => void;
  onAllocatorBusyChange: (busy: boolean) => void;
  onSnapshotStale: () => void;
  onActionReplace: (action: HandoverAction) => void;
  onExecuteRequest: () => void;
  onNextBatch: () => void;
}

/** previewed 段: 授权接收人 + 资产分配 + 重新预演/执行入口。 */
export function HandoverActionPreviewedSection({
  scope,
  task,
  action,
  readOnly,
  grantBusy,
  actionMutationLock,
  allocatorResetKey,
  previewPending,
  onPreview,
  onGrantReceiverChange,
  onAllocatorBusyChange,
  onSnapshotStale,
  onActionReplace,
  onExecuteRequest,
  onNextBatch,
}: HandoverActionPreviewedSectionProps) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      {task.kind === "offboard" ? (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-56">
            <p className="mb-1 text-caption text-ink-faint">{t("handover.wizard.grantReceiver")}</p>
            <HandoverUserPicker
              surface={scope.surface}
              taskId={task.id}
              value={action.grant_receiver}
              disabled={readOnly || actionMutationLock}
              onChange={(user) => onGrantReceiverChange(user?.user_id ?? null)}
            />
          </div>
          <p className="text-caption text-ink-faint">{t("handover.wizard.grantReceiverHint")}</p>
        </div>
      ) : null}
      <AssetAllocator
        key={allocatorResetKey}
        surface={scope.surface}
        taskId={task.id}
        action={action}
        readOnly={readOnly || grantBusy}
        onBusyChange={onAllocatorBusyChange}
        onSnapshotStale={onSnapshotStale}
        onActionUpdated={(patch) => {
          onActionReplace({
            ...action,
            asset_types: patch.asset_types ?? action.asset_types,
            confirm_version: patch.confirm_version ?? action.confirm_version,
            overrides_version: patch.overrides_version ?? action.overrides_version,
          });
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        {action.allowed_actions.includes("preview") ? (
          <Button
            type="button"
            size="sm"
            loading={previewPending}
            disabled={actionMutationLock && !previewPending}
            onClick={onPreview}
          >
            {t("handover.portal.detail.repreview")}
          </Button>
        ) : null}
        {action.batch_progress ? (
          <>
            <span className="text-caption text-ink-soft">
              {t("handover.portal.detail.batchProgress", {
                completed: action.batch_progress.completed,
                total: action.batch_progress.total,
              })}
            </span>
            <Button type="button" size="sm" variant="primary" disabled={actionMutationLock} onClick={onNextBatch}>
              {t("handover.portal.detail.nextBatch")}
            </Button>
            <span className="text-caption text-ink-faint">{t("handover.portal.detail.nextBatchHint")}</span>
          </>
        ) : action.allowed_actions.includes("execute") ? (
          <Button
            type="button"
            size="sm"
            variant="primary"
            disabled={actionMutationLock}
            data-testid="execute-handover"
            onClick={onExecuteRequest}
          >
            {t("handover.portal.detail.execute")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
