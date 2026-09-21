import { RefreshCcw } from "lucide-react";
import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

import { Button } from "../../../components/Button";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { useI18n } from "../../../i18n/I18nProvider";
import { UsageAlertsPanel } from "./usage/settings/UsageAlertsPanel";
import { StreamPausedBanner } from "./usage/settings/StreamPausedBanner";
import UsageSettingsButton from "./usage/settings/UsageSettingsButton";
import { UsageBreakdownStrip } from "./usage/UsageBreakdownStrip";
import { UsageCategoryTable } from "./usage/UsageCategoryTable";
import { UsageMeterCard } from "./usage/UsageMeterCard";
import { UsageRangeFilter } from "./usage/UsageRangeFilter";
import { UsageTrendChart } from "./usage/UsageTrendChart";
import { usageRangeFromSearchParams, usageRangeSearchUpdates, type UsageRangeKey } from "./usage/usageRange";
import type { UsageSummaryPayload } from "./usage/usageTypes";
import { useUsageSummary, useUsageTimeseries } from "./usage/useUsageData";

/**
 * 「状态健康 · 用量监控」标签页。
 *
 * 概览每 30 秒自动刷新一次, 时间范围只在图表上方出现一次并作用于下方所有图表与表格。
 */
export default function UsageMonitorTab() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const range = usageRangeFromSearchParams(searchParams);
  const summaryQuery = useUsageSummary();
  const timeseriesQuery = useUsageTimeseries(range);
  const summary = summaryQuery.data;

  const handleRangeChange = useCallback(
    (key: UsageRangeKey, from = "", to = "") => {
      setSearchParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          for (const [param, value] of Object.entries(usageRangeSearchUpdates(key, from, to))) {
            if (value === "") {
              next.delete(param);
            } else {
              next.set(param, value);
            }
          }
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const refresh = useCallback(() => {
    void summaryQuery.refetch();
    void timeseriesQuery.refetch();
  }, [summaryQuery, timeseriesQuery]);

  if (summaryQuery.error && !summary) {
    return <UsageLoadFailed error={summaryQuery.error as Error} isFetching={summaryQuery.isFetching} onRetry={refresh} />;
  }

  return (
    <div className="space-y-5">
      <UsageMonitorHeader
        isFetching={summaryQuery.isFetching}
        onRefresh={refresh}
        summary={summary}
      />
      <StreamPausedBanner />
      {summaryQuery.error ? (
        <StatusBanner
          live="alert"
          message={(summaryQuery.error as Error).message}
          title={t("usage.loadFailed")}
          tone="signal"
        />
      ) : null}
      <AuthentikNotice summary={summary} />

      <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-3">
        {summary ? (
          summary.metrics.map((metric) => <UsageMeterCard key={metric.metric} metric={metric} />)
        ) : (
          <MeterSkeletons />
        )}
      </div>
      {summary ? <UsageBreakdownStrip breakdown={summary.api_breakdown_today} /> : null}

      <UsageRangeFilter onChange={handleRangeChange} range={range} />
      <UsageTrendChart
        data={timeseriesQuery.data}
        error={(timeseriesQuery.error as Error | null) ?? null}
        isFetching={timeseriesQuery.isFetching}
        isLoading={timeseriesQuery.isLoading}
      />
      <UsageCategoryTable
        categories={timeseriesQuery.data?.categories ?? []}
        isLoading={timeseriesQuery.isLoading}
      />
      <UsageAlertsPanel />
    </div>
  );
}

/** 首屏占位: 三张与计量卡等高的骨架, 概览到位时不会让下方内容整体跳动。 */
function MeterSkeletons() {
  const { t } = useI18n();
  return (
    <>
      {[0, 1, 2].map((index) => (
        <div
          aria-label={t("common.loading")}
          className="h-56 animate-shimmer rounded-[3px] border border-ink/10"
          key={index}
          role="status"
        />
      ))}
    </>
  );
}

/** 顶部一行: 数据时间、手动刷新与用量设置入口。 */
function UsageMonitorHeader({
  isFetching,
  onRefresh,
  summary,
}: {
  isFetching: boolean;
  onRefresh: () => void;
  summary: UsageSummaryPayload | undefined;
}) {
  const { t, formatDateTime } = useI18n();

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
      <p className="text-body leading-5 text-ink-soft">{t("usage.header.description")}</p>
      <span className="ml-auto text-caption leading-4 text-ink-faint">
        {summary ? t("usage.header.updatedAt", { time: formatDateTime(summary.generated_at) }) : ""}
        <span className="ml-2">{t("usage.header.autoRefresh")}</span>
      </span>
      <Button icon={<RefreshCcw size={16} />} loading={isFetching} onClick={onRefresh} size="sm">
        {t("common.refresh")}
      </Button>
      <UsageSettingsButton variant="primary" />
    </div>
  );
}

/** Authentik 侧数据滞后或拉取失败时的提示; 两种情况文案不同, 但都不该让整页失败。 */
function AuthentikNotice({ summary }: { summary: UsageSummaryPayload | undefined }) {
  const { t, formatDateTime } = useI18n();
  if (!summary) {
    return null;
  }
  const { authentik } = summary;
  if (authentik.error) {
    return (
      <StatusBanner live="alert" message={authentik.error} title={t("usage.authentik.errorTitle")} tone="signal" />
    );
  }
  if (!authentik.stale) {
    return null;
  }
  return (
    <StatusBanner
      live="status"
      message={t("usage.authentik.staleMessage", {
        time: authentik.pulled_at ? formatDateTime(authentik.pulled_at) : t("usage.authentik.neverPulled"),
      })}
      title={t("usage.authentik.staleTitle")}
      tone="amber"
    />
  );
}

function UsageLoadFailed({
  error,
  isFetching,
  onRetry,
}: {
  error: Error;
  isFetching: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <PageState
      action={
        <Button icon={<RefreshCcw size={16} />} loading={isFetching} onClick={onRetry}>
          {t("common.retry")}
        </Button>
      }
      description={error.message}
      title={t("usage.loadFailed")}
      tone="signal"
    />
  );
}
