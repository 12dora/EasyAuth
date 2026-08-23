import { Activity, RefreshCcw } from "lucide-react";
import { useParams } from "react-router-dom";

import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PageState } from "../../components/ui/PageState";
import { useI18n } from "../../i18n/I18nProvider";
import { BlockedAppsOperationsSection } from "./operations/BlockedAppsSection";
import { OperationDialogs } from "./operations/OperationDialogs";
import { OperationFilters } from "./operations/OperationFilters";
import { OperationsTable } from "./operations/OperationsTable";
import { ENDPOINTS, type OperationSectionConfig } from "./operations/operationQuery";
import {
  useOperationsSection,
  type OperationsSectionController,
} from "./operations/useOperationsSection";

export function OperationsPage() {
  const { t } = useI18n();
  const { section = "access-requests" } = useParams();
  const config = ENDPOINTS[section];
  if (!config) {
    return (
      <PageState
        tone="neutral"
        title={t("notFound.title")}
        description={t("notFound.description")}
      />
    );
  }
  if (section === "blocked-apps") {
    return <BlockedAppsOperationsSection config={config} />;
  }
  return <OperationsSectionPage section={section} config={config} />;
}

function OperationsSectionPage({
  config,
  section,
}: {
  config: OperationSectionConfig;
  section: string;
}) {
  const { t } = useI18n();
  const controller = useOperationsSection(section, config);

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.operations")}
        title={t(config.titleKey)}
        description={t("console.operations.description")}
        actions={<OperationsHeaderActions controller={controller} />}
      />
      {controller.isPaginated ? (
        <OperationFilters
          section={section}
          searchParams={controller.searchParams}
          onChange={controller.updateSearchParam}
        />
      ) : null}
      <OperationsNotices controller={controller} />
      <OperationsResult controller={controller} />
      <OperationDialogs controller={controller} />
    </>
  );
}

/** 有数据时故障降级为顶部横幅, 无数据时由 OperationsResult 接管整页状态。 */
function OperationsNotices({
  controller,
}: {
  controller: OperationsSectionController;
}) {
  const { t } = useI18n();
  const { query, rows, operationNotice } = controller;

  return (
    <>
      {query.error && rows.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("console.operations.loadFailed")} message={(query.error as Error).message} />
      ) : null}
      {operationNotice ? (
        <StatusBanner live="alert" tone={operationNotice.tone} title={operationNotice.title} message={operationNotice.message} />
      ) : null}
    </>
  );
}

function OperationsResult({
  controller,
}: {
  controller: OperationsSectionController;
}) {
  const { t } = useI18n();
  const { query, rows } = controller;

  if (query.error && rows.length === 0) {
    return (
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
    );
  }
  return (
    <OperationsTable
      table={controller.table}
      isLoading={query.isLoading}
      totalItems={query.data?.pagination?.total_items ?? rows.length}
    />
  );
}

function OperationsHeaderActions({
  controller,
}: {
  controller: OperationsSectionController;
}) {
  const { t } = useI18n();
  const { query, healthCheckMutation } = controller;

  return (
    <>
      {controller.section === "dependency-health" ? (
        <Button
          variant="primary"
          icon={<Activity size={16} />}
          loading={healthCheckMutation.isPending}
          onClick={() => healthCheckMutation.mutate()}
        >
          {t("ops.dependencyHealth.runCheck")}
        </Button>
      ) : null}
      <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
        {t("common.refresh")}
      </Button>
    </>
  );
}
