import { ApprovalDecisionDialog } from "../../../components/ApprovalDecisionDialog";
import { useI18n } from "../../../i18n/I18nProvider";

import { decisionDetails } from "./PortalApprovalDetails";
import { applicantLabel, approvalIsDecidable } from "./portalApprovalFacts";
import type { ApprovalDetailState, PendingDecision } from "./portalApprovalTypes";

/** 同意/驳回弹窗: 只有详情已复核且申请仍可决定时才允许提交。 */
export function PortalApprovalDecisionPrompt({
  pendingDecision,
  detail,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  pendingDecision: PendingDecision;
  detail: ApprovalDetailState;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (decision: PendingDecision & { comment: string }) => void;
}) {
  const { t } = useI18n();
  const decisionApproval = !detail.isFetching && !detail.error ? detail.approval : undefined;
  const canSubmit = Boolean(decisionApproval && approvalIsDecidable(decisionApproval, pendingDecision.approval.id));

  return (
    <ApprovalDecisionDialog
      mode={pendingDecision.mode}
      description={t(
        pendingDecision.mode === "approve" ? "portal.approvals.approveDescription" : "portal.approvals.rejectDescription",
        {
          applicant: applicantLabel(pendingDecision.approval),
          app: pendingDecision.approval.app_name ?? pendingDecision.approval.app_key ?? "-",
        },
      )}
      details={decisionDetails(t, detail.approval, detail.isLoading, detail.error)}
      errorMessage={errorMessage}
      isSubmitting={isSubmitting}
      canSubmit={canSubmit}
      onClose={onClose}
      onSubmit={(comment) => {
        if (decisionApproval && canSubmit) {
          onSubmit({ mode: pendingDecision.mode, approval: decisionApproval, comment });
        }
      }}
    />
  );
}
