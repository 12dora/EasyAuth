import { getCoreRowModel, useReactTable } from "@tanstack/react-table";

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
    pagination,
    setPagination,
    clampedPageIndex,
    totalPages,
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
  const table = useReactTable({
    data: approvals,
    columns: approvalColumns(t, tab, isSubmitting, openDecision),
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: totalPages,
    state: { pagination: { ...pagination, pageIndex: clampedPageIndex } },
    onPaginationChange: setPagination,
  });

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
            table={table}
            tab={tab}
            isLoading={query.isLoading}
            totalItems={query.data?.pagination.total_items ?? approvals.length}
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
