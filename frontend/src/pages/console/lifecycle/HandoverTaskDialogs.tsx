import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { TextArea } from "../../../components/Field";
import { useI18n } from "../../../i18n/I18nProvider";
import type { useHandoverTaskDetail } from "./useHandoverTaskDetail";

export interface TaskConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  loading: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

/** 取消/删除任务共用的二次确认弹窗。 */
export function TaskConfirmDialog({
  title,
  message,
  confirmLabel,
  loading,
  onClose,
  onConfirm,
}: TaskConfirmDialogProps) {
  const { t } = useI18n();
  return (
    <Dialog
      title={title}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="button" variant="danger" loading={loading} disabled={loading} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-body leading-5 text-ink-soft">{message}</p>
    </Dialog>
  );
}

export interface DeferDialogProps {
  reason: string;
  loading: boolean;
  onReasonChange: (value: string) => void;
  onClose: () => void;
  onConfirm: () => void;
}

export function DeferDialog({ reason, loading, onReasonChange, onClose, onConfirm }: DeferDialogProps) {
  const { t } = useI18n();
  return (
    <Dialog
      title={t("handover.console.deferTitle")}
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
            disabled={reason.trim().length < 10}
            loading={loading}
            onClick={onConfirm}
          >
            {t("handover.console.deferConfirm")}
          </Button>
        </>
      }
    >
      <TextArea
        value={reason}
        aria-label={t("handover.console.deferReason")}
        onChange={(event) => onReasonChange(event.currentTarget.value)}
      />
    </Dialog>
  );
}

/** 详情页三个任务级弹窗的挂载点: 延期 / 删除 / 取消。 */
export function TaskDetailDialogs({
  detail,
  subjectName,
}: {
  detail: ReturnType<typeof useHandoverTaskDetail>;
  subjectName: string;
}) {
  const { t } = useI18n();
  return (
    <>
      {detail.deferOpen ? (
        <DeferDialog
          reason={detail.deferReason}
          loading={detail.deferMutation.isPending}
          onReasonChange={detail.setDeferReason}
          onClose={detail.closeDefer}
          onConfirm={() => detail.deferMutation.mutate()}
        />
      ) : null}

      {detail.deleteConfirmOpen && detail.task ? (
        <TaskConfirmDialog
          title={t("handover.detail.deleteTask")}
          message={t("handover.detail.deleteMessage", { name: subjectName })}
          confirmLabel={t("handover.detail.deleteConfirm")}
          loading={detail.deleteMutation.isPending}
          onClose={detail.closeDeleteConfirm}
          onConfirm={() => detail.deleteMutation.mutate()}
        />
      ) : null}
      {detail.cancelConfirmOpen && detail.task ? (
        <TaskConfirmDialog
          title={t("handover.detail.cancelTask")}
          message={t("handover.detail.cancelMessage", { name: subjectName })}
          confirmLabel={t("handover.detail.cancelConfirm")}
          loading={detail.cancelMutation.isPending}
          onClose={detail.closeCancelConfirm}
          onConfirm={() => detail.cancelMutation.mutate()}
        />
      ) : null}
    </>
  );
}
