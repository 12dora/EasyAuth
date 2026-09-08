import { ApprovalDecisionDialog } from "../../../components/ApprovalDecisionDialog";
import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import { useI18n } from "../../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { AccessGrantRow } from "../../../lib/domain/accessGrantRow";
import { dialogErrorMessage } from "./operationErrors";
import { ReasonActionDialog } from "./ReasonActionDialog";
import { ReassignApproversDialog } from "./ReassignApproversDialog";
import { operationAppDisplayName, stringValue } from "./operationRow";
import type { OperationRow } from "./operationRow";
import type { Translator } from "../../../lib/status";
import type { OperationsSectionController } from "./useOperationsSection";

/** 弹窗里的操作对象一律按姓名与应用展示名描述; 目录里没有姓名时才回落到 user_id。 */
function rowTarget(t: Translator, row: OperationRow): string {
  return t("console.accessRequests.target", {
    user: row.user_name || stringValue(row.user_id),
    app: operationAppDisplayName(row),
  });
}

function grantTarget(row: AccessGrantRow): { user: string; app: string } {
  return {
    user: row.user_name || row.user_id,
    app: formatAppDisplayName({ name: row.app_name, alias: row.app_alias }),
  };
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
            user: pendingAction.row.user_name || stringValue(pendingAction.row.user_id),
            app: operationAppDisplayName(pendingAction.row),
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
          description={t("console.operations.emergencyRevokeDescription", grantTarget(pendingEmergencyRevoke))}
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
