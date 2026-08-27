import { Activity, RefreshCcw } from "lucide-react";
import { useId } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { Button } from "../../components/Button";
import { TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PageState } from "../../components/ui/PageState";
import { useI18n } from "../../i18n/I18nProvider";
import { BlockedAppsOperationsSection } from "./operations/BlockedAppsSection";
import { OperationDialogs } from "./operations/OperationDialogs";
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
      {section === "access-grants" ? (
        <GrantCreatedRangeFilter
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
  return <OperationsTable controller={controller} />;
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

/**
 * 授权列表的时间范围筛选。
 *
 * 全站唯一保留在表格上方的筛选控件: 后端支持 created_from/created_to,
 * 但授权列表的载荷里没有 created_at 字段, 没有对应的列可以挂表头筛选
 * (其余分区都走列上的共享 dateRangeFilter)。
 */
function GrantCreatedRangeFilter({
  searchParams,
  onChange,
}: {
  searchParams: URLSearchParams;
  onChange: (key: string, value: string) => void;
}) {
  const { t } = useI18n();
  const [, setSearchParams] = useSearchParams();
  const labelId = useId();
  const startLabelId = useId();
  const endLabelId = useId();
  const createdFrom = searchParams.get("created_from") ?? "";
  const createdTo = searchParams.get("created_to") ?? "";

  // 清空必须一次写回: onChange 逐个调用会各自基于同一份旧 searchParams, 后一次会把前一次的删除覆盖掉。
  const clearRange = () => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.delete("created_from");
      next.delete("created_to");
      next.set("page", "1");
      return next;
    });
  };

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 sm:flex-nowrap">
      <span id={labelId} className="shrink-0 text-label uppercase tracking-caps-wide text-ink-soft font-medium">
        {t("console.operations.grants.createdRange")}
      </span>
      <span id={startLabelId} className="sr-only">
        {t("console.operations.grants.createdRangeStart")}
      </span>
      <TextInput
        aria-labelledby={`${labelId} ${startLabelId}`}
        className="w-52"
        type="datetime-local"
        value={createdFrom}
        onChange={(event) => onChange("created_from", event.currentTarget.value)}
      />
      <span aria-hidden="true" className="shrink-0 text-ink-faint">
        &mdash;
      </span>
      <span id={endLabelId} className="sr-only">
        {t("console.operations.grants.createdRangeEnd")}
      </span>
      <TextInput
        aria-labelledby={`${labelId} ${endLabelId}`}
        className="w-52"
        type="datetime-local"
        value={createdTo}
        onChange={(event) => onChange("created_to", event.currentTarget.value)}
      />
      {createdFrom || createdTo ? (
        <Button size="sm" variant="ghost" onClick={clearRange}>
          {t("common.clear")}
        </Button>
      ) : null}
    </div>
  );
}
