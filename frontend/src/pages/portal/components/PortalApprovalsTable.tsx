import { RefreshCcw } from "lucide-react";

import { Button } from "../../../components/Button";
import { AppTable, type ColumnsType, type UseServerTableResult } from "../../../components/antd/AppTable";
import { PageState } from "../../../components/ui/PageState";
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
  columns,
  rows,
  serverTable,
  tab,
  isLoading,
}: {
  columns: ColumnsType<PortalApprovalRow>;
  rows: PortalApprovalRow[];
  serverTable: UseServerTableResult<PortalApprovalRow>;
  tab: ApprovalTab;
  isLoading: boolean;
}) {
  const { t } = useI18n();
  return (
    <AppTable<PortalApprovalRow>
      {...serverTable.tableProps}
      ariaLabel={t("portal.approvals.ariaLabel")}
      columns={columns}
      dataSource={rows}
      emptyDescription={
        tab === "pending"
          ? t("portal.approvals.empty.pendingDescription")
          : t("portal.approvals.empty.processedDescription")
      }
      emptyTitle={tab === "pending" ? t("portal.approvals.empty.pending") : t("portal.approvals.empty.processed")}
      loading={isLoading}
      minWidth={1200}
      rowKey="id"
    />
  );
}
