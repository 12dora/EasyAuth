import { Button } from "../Button";
import { Dialog } from "../Dialog";
import { useI18n } from "../../i18n/I18nProvider";

/** 通用二次确认弹窗: 用于表格操作列的删除等不可逆动作, 统一确认/取消布局。 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  danger = true,
  confirming = false,
  onConfirm,
  onClose,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  confirming?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      title={title}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={confirming}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant={danger ? "danger" : "primary"}
            loading={confirming}
            disabled={confirming}
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="text-body leading-5 text-ink-soft">{message}</p>
    </Dialog>
  );
}
