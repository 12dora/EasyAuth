import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { ConnectorInstanceFormController } from "./useConnectorInstanceForm";

export function ConnectorDeleteDialog({
  controller,
}: {
  controller: ConnectorInstanceFormController;
}) {
  const { t } = useI18n();
  const { canManage, drafts, mutations } = controller;
  const { deleteMutation } = mutations;
  const close = () => drafts.setDeleteConfirmOpen(false);

  return (
    <Dialog
      title={t("console.connector.deleteTitle")}
      size="sm"
      onClose={close}
      footer={
        <>
          <Button type="button" onClick={close}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="danger"
            loading={deleteMutation.isPending}
            disabled={deleteMutation.isPending || !canManage}
            onClick={() => deleteMutation.mutate()}
          >
            {t("console.connector.deleteConfirm")}
          </Button>
        </>
      }
    >
      <p className="text-body leading-6 text-ink">
        {t("console.connector.deleteMessage")}
      </p>
    </Dialog>
  );
}
