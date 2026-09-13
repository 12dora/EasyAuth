import { Activity, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { DateRangeControl } from "../../components/antd/AppTable";
import { Button } from "../../components/Button";
import { TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PageState } from "../../components/ui/PageState";
import { useI18n } from "../../i18n/I18nProvider";
import { BlockedAppsOperationsSection } from "./operations/BlockedAppsSection";
import { OperationDialogs } from "./operations/OperationDialogs";
import { OperationsTable } from "./operations/OperationsTable";
import {
  ENDPOINTS,
  INCLUDE_HISTORY_PARAM,
  USER_QUERY_PARAM,
  includeHistoryFromSearchParams,
  type OperationSectionConfig,
} from "./operations/operationQuery";
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
        description={t(config.descriptionKey ?? "console.operations.description")}
        actions={<OperationsHeaderActions controller={controller} />}
      />
      {section === "access-grants" ? (
        <GrantFilters
          searchParams={controller.searchParams}
          onChange={controller.updateSearchParam}
          onChangeParams={controller.updateSearchParams}
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
  const { query, rowCount, operationNotice } = controller;

  return (
    <>
      {query.error && rowCount > 0 ? (
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
  const { query, rowCount, table } = controller;

  if (query.error && rowCount === 0) {
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
  // 授权明细与其余分区的行类型不同, 列定义无法互相赋值, 因此在这里判别后各自实例化。
  return table.kind === "grants" ? (
    <OperationsTable
      columns={table.columns}
      isLoading={query.isLoading}
      minWidth={table.minWidth}
      rowKey={table.rowKey}
      rows={table.rows}
      tableProps={table.tableProps}
    />
  ) : (
    <OperationsTable
      columns={table.columns}
      isLoading={query.isLoading}
      minWidth={table.minWidth}
      rowKey={table.rowKey}
      rows={table.rows}
      tableProps={table.tableProps}
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

/**
 * 授权明细表格上方的筛选条。
 *
 * 用户模糊搜索与创建时间都没有列可以挂表头筛选(用户列仍是 user_id 精确筛选):
 * 后端支持 created_from/created_to, 但授权载荷里没有 created_at 字段;
 * 「包含历史版本」控制的是列表口径本身(`current_only`), 不是某一列的取值。
 * 日期范围控件与表头 `dateRangeFilter` 共用 `DateRangeControl`。
 */
function GrantFilters({
  onChange,
  onChangeParams,
  searchParams,
}: {
  searchParams: URLSearchParams;
  onChange: (key: string, value: string) => void;
  onChangeParams: (updates: Record<string, string>) => void;
}) {
  const { t } = useI18n();
  const urlQuery = searchParams.get(USER_QUERY_PARAM) ?? "";
  const [userQuery, setUserQuery] = useState(urlQuery);

  useEffect(() => {
    setUserQuery(urlQuery);
  }, [urlQuery]);

  useEffect(() => {
    const trimmed = userQuery.trim();
    if (trimmed === urlQuery) {
      return;
    }
    const timer = window.setTimeout(() => onChange(USER_QUERY_PARAM, trimmed), 250);
    return () => window.clearTimeout(timer);
  }, [onChange, urlQuery, userQuery]);

  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <TextInput
        aria-label={t("console.operations.userQueryPlaceholder")}
        autoComplete="off"
        className="w-64"
        placeholder={t("console.operations.userQueryPlaceholder")}
        value={userQuery}
        onChange={(event) => setUserQuery(event.currentTarget.value)}
      />
      <DateRangeControl
        ariaLabel={t("console.operations.grants.createdRange")}
        value={{
          from: searchParams.get("created_from") ?? "",
          to: searchParams.get("created_to") ?? "",
        }}
        onChange={(range) => onChangeParams({ created_from: range.from, created_to: range.to })}
      />
      <label className="ml-auto inline-flex shrink-0 items-center gap-2 text-body text-ink">
        <input
          type="checkbox"
          checked={includeHistoryFromSearchParams(searchParams)}
          onChange={(event) => onChange(INCLUDE_HISTORY_PARAM, event.currentTarget.checked ? "1" : "")}
        />
        <span>{t("console.operations.filter.includeHistory")}</span>
      </label>
    </div>
  );
}
