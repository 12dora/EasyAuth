import { Suspense, lazy } from "react";

import { Badge } from "../../../../components/Badge";
import { StatusBanner } from "../../../../components/StatusBanner";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import {
  USAGE_ALL_SERIES,
  USAGE_SERIES_LABEL_KEYS,
  hasAnyUsage,
  toUsageChartRows,
} from "./usageChartModel";
import { formatUsageCount } from "./usageMeterModel";
import type { UsageTimeseriesPayload } from "./usageTypes";

const LazyUsageTrendChartImpl = lazy(() => import("./UsageTrendChartImpl"));

export interface UsageTrendChartProps {
  data: UsageTimeseriesPayload | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
}

/**
 * 趋势图卡片: 标题、粒度、区间合计与各种非数据状态都在这一层,
 * recharts 本体放在独立的异步 chunk 里(`UsageTrendChartImpl`), 首屏不拉图表库。
 */
export function UsageTrendChart({ data, isLoading, isFetching, error }: UsageTrendChartProps) {
  const { t } = useI18n();

  return (
    <PanelSurface padding="lg" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold leading-tight text-ink">{t("usage.trend.title")}</h3>
          {data ? (
            <Badge tone="faint">
              {t(data.granularity === "hour" ? "usage.trend.granularityHour" : "usage.trend.granularityDay")}
            </Badge>
          ) : null}
        </div>
        <p className="text-caption leading-4 text-ink-faint">{t("usage.trend.legendHint")}</p>
      </div>

      {data ? <TrendTotals data={data} /> : null}

      <TrendBody data={data} error={error} isFetching={isFetching} isLoading={isLoading} />
    </PanelSurface>
  );
}

/** 区间合计直接写成文字: 图表的每个数值都有不靠悬浮也能读到的去处。 */
function TrendTotals({ data }: { data: UsageTimeseriesPayload }) {
  const { t, locale } = useI18n();

  return (
    <dl className="flex flex-wrap gap-x-5 gap-y-1.5 border-y border-ink/10 py-2">
      <dt className="text-caption leading-4 text-ink-faint">{t("usage.trend.totalsLabel")}</dt>
      {USAGE_ALL_SERIES.map((key) => (
        <dd className="flex items-baseline gap-1.5 text-caption leading-4 text-ink-soft" key={key}>
          {t(USAGE_SERIES_LABEL_KEYS[key])}
          <span className="font-mono font-semibold text-ink">{formatUsageCount(data.totals[key], locale)}</span>
        </dd>
      ))}
    </dl>
  );
}

function TrendBody({
  data,
  error,
  isFetching,
  isLoading,
}: {
  data: UsageTimeseriesPayload | undefined;
  error: Error | null;
  isFetching: boolean;
  isLoading: boolean;
}) {
  const { t } = useI18n();

  if (error && !data) {
    return <StatusBanner live="alert" tone="signal" title={t("usage.timeseriesFailed")} message={error.message} />;
  }
  if (isLoading || !data) {
    return <div aria-label={t("usage.trend.loading")} className="h-64 w-full animate-shimmer rounded-[3px]" role="status" />;
  }
  if (!hasAnyUsage(data.points)) {
    return <EmptyState title={t("usage.trend.emptyTitle")} description={t("usage.trend.emptyDescription")} />;
  }

  return (
    <Suspense
      fallback={<div aria-label={t("usage.trend.loading")} className="h-64 w-full animate-shimmer rounded-[3px]" role="status" />}
    >
      <LazyUsageTrendChartImpl dimmed={isFetching} rows={toUsageChartRows(data.points, data.granularity)} />
    </Suspense>
  );
}
