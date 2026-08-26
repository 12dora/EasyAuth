import { RefreshCcw } from "lucide-react";

import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PageState } from "../../components/ui/PageState";
import { useI18n } from "../../i18n/I18nProvider";
import { ApprovalInstancesTable } from "./ApprovalInstancesTable";
import { useApprovalInstances } from "./useApprovalInstances";

export function ApprovalInstancesPage() {
  const { t } = useI18n();
  const page = useApprovalInstances();
  const { query, rows } = page;

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t("nav.console.approvalInstances")}
        description={t("approvalInstances.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      {query.error && rows.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("console.operations.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {query.error && rows.length === 0 ? (
        <PageState
          tone="signal"
          title={t("console.operations.loadFailed")}
          description={(query.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <ApprovalInstancesTable
          rows={rows}
          isLoading={query.isLoading}
          tableProps={page.tableProps}
          actions={{ isDisabled: page.isRedelivering, onRedeliver: page.redeliver }}
        />
      )}
    </>
  );
}
