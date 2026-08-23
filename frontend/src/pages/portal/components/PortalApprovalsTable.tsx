import type { Table } from "@tanstack/react-table";
import { RefreshCcw } from "lucide-react";

import { Button } from "../../../components/Button";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PageState } from "../../../components/ui/PageState";
import { TableView } from "../../../components/ui/TableView";
import { useI18n } from "../../../i18n/I18nProvider";

import type { ApprovalTab, PortalApprovalRow } from "./portalApprovalTypes";

/** 列表整体加载失败(且无可展示行)时替代表格的重试态。 */
export function ApprovalsLoadFailure({
  message,
  isRetrying,
  onRetry,
}: {
  message: string;
  isRetrying: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <PageState
      tone="signal"
      title={t("portal.approvals.loadFailed")}
      description={message}
      action={
        <Button icon={<RefreshCcw size={16} />} loading={isRetrying} onClick={onRetry}>
          {t("common.retry")}
        </Button>
      }
    />
  );
}

export function PortalApprovalsTable({
  table,
  tab,
  isLoading,
  totalItems,
}: {
  table: Table<PortalApprovalRow>;
  tab: ApprovalTab;
  isLoading: boolean;
  totalItems: number;
}) {
  const { t } = useI18n();
  return (
    <TableView
      table={table}
      ariaLabel={t("nav.portal.myApprovals")}
      isLoading={isLoading}
      totalItems={totalItems}
      empty={
        <EmptyState
          title={tab === "pending" ? t("portal.approvals.empty.pending") : t("portal.approvals.empty.processed")}
          description={
            tab === "pending"
              ? t("portal.approvals.empty.pendingDescription")
              : t("portal.approvals.empty.processedDescription")
          }
        />
      }
    />
  );
}
