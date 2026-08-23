import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, SelectInput, TextArea } from "../../components/Field";
import { useI18n } from "../../i18n/I18nProvider";
import type { HandoverAction } from "../../lib/domain";
import { buildExecuteConfirmParts } from "./assetAllocatorModel";
import { resolveConfirmReceiver } from "./handoverActionPanelModel";
import type { useHandoverActionPanel } from "./useHandoverActionPanel";

export function ExecuteConfirmDialog({
  action,
  loading,
  disabled,
  onClose,
  onConfirm,
}: {
  action: HandoverAction;
  loading: boolean;
  disabled: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const confirmParts = buildExecuteConfirmParts(action);
  const primaryReceiver = resolveConfirmReceiver(confirmParts, action, t);
  return (
    <Dialog
      title={t("handover.portal.detail.executeConfirmTitle")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="primary"
            loading={loading}
            disabled={disabled}
            data-testid="execute-confirm"
            onClick={onConfirm}
          >
            {t("handover.portal.detail.executeConfirm")}
          </Button>
        </>
      }
    >
      <p className="text-body leading-5 text-ink-soft" data-testid="execute-confirm-body">
        {confirmParts.uniqueReceiverNames.length > 1
          ? t("handover.portal.detail.executeConfirmBodyMulti", {
              assets: confirmParts.transferLines.join("、") || "-",
              count: confirmParts.uniqueReceiverNames.length,
              overrides: confirmParts.overrideCount,
            })
          : t("handover.portal.detail.executeConfirmBody", {
              assets: confirmParts.transferLines.join("、") || "-",
              receiver: primaryReceiver,
              overrides: confirmParts.overrideCount,
            })}
      </p>
    </Dialog>
  );
}

export function SkipActionDialog({
  reason,
  loading,
  onReasonChange,
  onClose,
  onConfirm,
}: {
  reason: string;
  loading: boolean;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      title={t("handover.console.skipTitle")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="danger"
            disabled={reason.trim().length < 10}
            loading={loading}
            onClick={onConfirm}
          >
            {t("handover.console.skipConfirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-body text-signal">{t("handover.console.skipWarning")}</p>
        <TextArea
          value={reason}
          aria-label={t("handover.console.skipReason")}
          onChange={(event) => onReasonChange(event.currentTarget.value)}
        />
      </div>
    </Dialog>
  );
}

export function AsyncAbandonDialog({
  outcome,
  reason,
  loading,
  onOutcomeChange,
  onReasonChange,
  onClose,
  onConfirm,
}: {
  outcome: "done" | "failed";
  reason: string;
  loading: boolean;
  onOutcomeChange: (value: "done" | "failed") => void;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      title={t("handover.console.asyncAbandonTitle")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="danger"
            disabled={reason.trim().length < 10}
            loading={loading}
            onClick={onConfirm}
          >
            {t("handover.console.asyncAbandonConfirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="text-body text-ink-soft">{t("handover.console.asyncAbandonHint")}</p>
        <Field label={t("handover.console.asyncAbandonOutcome")}>
          <SelectInput
            value={outcome}
            aria-label={t("handover.console.asyncAbandonOutcome")}
            onChange={(event) => onOutcomeChange(event.currentTarget.value as "done" | "failed")}
          >
            <option value="done">{t("handover.console.asyncAbandonOutcomeDone")}</option>
            <option value="failed">{t("handover.console.asyncAbandonOutcomeFailed")}</option>
          </SelectInput>
        </Field>
        <Field label={t("handover.console.asyncAbandonReason")} hint={t("handover.portal.reassign.reasonHint")}>
          <TextArea
            value={reason}
            aria-label={t("handover.console.asyncAbandonReason")}
            onChange={(event) => onReasonChange(event.currentTarget.value)}
          />
        </Field>
      </div>
    </Dialog>
  );
}

/** 交接卡三个弹窗的挂载点: 执行确认 / 跳过 / 异步放弃。 */
export function ActionPanelDialogs({
  action,
  panel,
}: {
  action: HandoverAction;
  panel: ReturnType<typeof useHandoverActionPanel>;
}) {
  return (
    <>
      {panel.confirmOpen ? (
        <ExecuteConfirmDialog
          action={action}
          loading={panel.executeMutation.isPending}
          disabled={panel.actionMutationLock && !panel.executeMutation.isPending}
          onClose={panel.closeConfirm}
          onConfirm={() => panel.executeMutation.mutate()}
        />
      ) : null}

      {panel.skipOpen ? (
        <SkipActionDialog
          reason={panel.skipReason}
          loading={panel.skipMutation.isPending}
          onReasonChange={panel.setSkipReason}
          onClose={panel.closeSkip}
          onConfirm={() => panel.skipMutation.mutate()}
        />
      ) : null}

      {panel.asyncAbandonOpen ? (
        <AsyncAbandonDialog
          outcome={panel.asyncOutcome}
          reason={panel.asyncReason}
          loading={panel.asyncAbandonMutation.isPending}
          onOutcomeChange={panel.setAsyncOutcome}
          onReasonChange={panel.setAsyncReason}
          onClose={panel.closeAsyncAbandon}
          onConfirm={() => panel.asyncAbandonMutation.mutate()}
        />
      ) : null}
    </>
  );
}

