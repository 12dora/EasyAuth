import { ApprovalDecisionDialog } from "../../../components/ApprovalDecisionDialog";
import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { useI18n } from "../../../i18n/I18nProvider";
import { dialogErrorMessage } from "./operationErrors";
import { ReasonActionDialog } from "./ReasonActionDialog";
import { ReassignApproversDialog } from "./ReassignApproversDialog";
import { stringValue } from "./operationRow";
import type { OperationRow } from "./operationRow";
import type { Translator } from "../../../lib/status";
import type { OperationsSectionController } from "./useOperationsSection";

function rowTarget(t: Translator, row: OperationRow): string {
  return t("console.accessRequests.target", {
    user: stringValue(row.user_id),
    app: stringValue(row.app_key),
  });
}

export function OperationDialogs({
  controller,
}: {
  controller: OperationsSectionController;
}) {
  const { t } = useI18n();
  const { pendingAction, pendingEmergencyRevoke, accessRequestMutations } = controller;
  const { decisionMutation, reassignMutation, retryGrantMutation } = accessRequestMutations;

  return (
    <>
      {pendingAction && (pendingAction.type === "approve" || pendingAction.type === "reject") ? (
        <ApprovalDecisionDialog
          mode={pendingAction.type}
          description={rowTarget(t, pendingAction.row)}
          note={t("console.accessRequests.auditNote")}
          errorMessage={dialogErrorMessage(decisionMutation.error, { hideConflict: true, hideDecisionCommitted: true })}
          isSubmitting={decisionMutation.isPending}
          onClose={controller.closePendingAction}
          onSubmit={(comment) => decisionMutation.mutate({ type: pendingAction.type as ApprovalDecisionMode, row: pendingAction.row, comment })}
        />
      ) : null}
      {pendingAction?.type === "reassign" ? (
        <ReassignApproversDialog
          description={rowTarget(t, pendingAction.row)}
          errorMessage={dialogErrorMessage(reassignMutation.error, { hideConflict: true })}
          isSubmitting={reassignMutation.isPending}
          onClose={controller.closePendingAction}
          onSubmit={(approverUserIds) => reassignMutation.mutate({ row: pendingAction.row, approverUserIds })}
        />
      ) : null}
      {pendingAction?.type === "retry-grant" ? (
        <ReasonActionDialog
          title={t("console.operations.retryGrant")}
          description={t("console.operations.retryGrantDescription", {
            user: stringValue(pendingAction.row.user_id),
            app: stringValue(pendingAction.row.app_key),
          })}
          confirmLabel={t("console.operations.retryGrant")}
          errorTitle={t("console.operations.retryGrantFailed")}
          errorMessage={dialogErrorMessage(retryGrantMutation.error)}
          isSubmitting={retryGrantMutation.isPending}
          onClose={controller.closePendingAction}
          onSubmit={(reason) => retryGrantMutation.mutate({ row: pendingAction.row, reason })}
        />
      ) : null}
      {pendingEmergencyRevoke ? (
        <ReasonActionDialog
          title={t("console.operations.emergencyRevoke")}
          description={t("console.operations.emergencyRevokeDescription", {
            user: stringValue(pendingEmergencyRevoke.user_id),
            app: stringValue(pendingEmergencyRevoke.app_key),
          })}
          confirmLabel={t("console.operations.emergencyRevoke")}
          errorTitle={t("console.operations.emergencyRevokeFailed")}
          errorMessage={dialogErrorMessage(controller.emergencyRevokeMutation.error)}
          isSubmitting={controller.emergencyRevokeMutation.isPending}
          onClose={controller.closeEmergencyRevoke}
          onSubmit={(reason) => controller.emergencyRevokeMutation.mutate({ row: pendingEmergencyRevoke, reason })}
        />
      ) : null}
    </>
  );
}
