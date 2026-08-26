import { useMemo } from "react";

import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";

import { PortalApprovalDecisionPrompt } from "./PortalApprovalDecisionPrompt";
import { PortalApprovalNotice } from "./PortalApprovalNotice";
import { ApprovalsLoadFailure, PortalApprovalsTable } from "./PortalApprovalsTable";
import { PortalApprovalsTabs } from "./PortalApprovalsTabs";
import { approvalColumns } from "./portalApprovalColumns";
import { usePortalApprovals } from "./usePortalApprovals";

export function PortalApprovalsSection() {
  const { t } = useI18n();
  const {
    tab,
    switchTab,
    serverTable,
    query,
    approvals,
    detail,
    noticeKey,
    pendingDecision,
    openDecision,
    closeDecision,
    submitDecision,
    isSubmitting,
    dialogErrorMessage,
  } = usePortalApprovals();
  const sort = serverTable.query;
  const columns = useMemo(
    () => approvalColumns(t, tab, sort, isSubmitting, openDecision),
    [isSubmitting, openDecision, sort, t, tab],
  );

  return (
    <>
      <PortalApprovalsTabs tab={tab} onSwitchTab={switchTab} />
      <PortalApprovalNotice noticeKey={noticeKey} />
      {query.error && approvals.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("portal.approvals.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      <div id={`portal-approvals-tabpanel-${tab}`} role="tabpanel" aria-labelledby={`portal-approvals-tab-${tab}`}>
        {query.error && approvals.length === 0 ? (
          <ApprovalsLoadFailure
            message={(query.error as Error).message}
            isRetrying={query.isFetching}
            onRetry={() => void query.refetch()}
          />
        ) : (
          <PortalApprovalsTable
            columns={columns}
            isLoading={query.isLoading}
            rows={approvals}
            serverTable={serverTable}
            tab={tab}
          />
        )}
      </div>
      {pendingDecision ? (
        <PortalApprovalDecisionPrompt
          pendingDecision={pendingDecision}
          detail={detail}
          errorMessage={dialogErrorMessage}
          isSubmitting={isSubmitting}
          onClose={closeDecision}
          onSubmit={submitDecision}
        />
      ) : null}
    </>
  );
}
