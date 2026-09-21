import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import { USAGE_SERIES_COLOR } from "./usageChartTheme";
import { formatUsageCount, formatUsagePercent, sharePercent } from "./usageMeterModel";
import type { UsageApiBreakdown } from "./usageTypes";

interface BreakdownSegment {
  key: "billed" | "unbilled" | "internal";
  labelKey: MessageKey;
  color: string;
  value: number;
}

function segments(breakdown: UsageApiBreakdown): BreakdownSegment[] {
  return [
    { key: "billed", labelKey: "usage.breakdown.billed", color: USAGE_SERIES_COLOR.api_billed, value: breakdown.billed },
    {
      key: "unbilled",
      labelKey: "usage.breakdown.unbilled",
      color: USAGE_SERIES_COLOR.api_unbilled,
      value: breakdown.unbilled,
    },
    {
      key: "internal",
      labelKey: "usage.breakdown.internal",
      color: USAGE_SERIES_COLOR.internal,
      value: breakdown.internal,
    },
  ];
}

/**
 * 今日 API 调用构成: 一条按比例分段的横条 + 图例。
 *
 * 段与段之间留 2px 背景色缝(不画描边), 宽度变化走 CSS 过渡。
 * 每个分段的数值都写在图例里, 不依赖 hover 才能读到。
 */
export function UsageBreakdownStrip({ breakdown }: { breakdown: UsageApiBreakdown }) {
  const { t, locale } = useI18n();
  const all = segments(breakdown);
  const total = breakdown.total;

  return (
    <PanelSurface padding="lg" className="space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-semibold leading-tight text-ink">{t("usage.breakdown.title")}</h3>
        <p className="text-caption leading-4 text-ink-faint">
          {t("usage.breakdown.total")}
          <span className="ml-1.5 font-mono text-body font-semibold text-ink">
            {formatUsageCount(total, locale)}
          </span>
        </p>
      </div>

      {total <= 0 ? (
        <p className="text-caption leading-5 text-ink-faint">{t("usage.breakdown.empty")}</p>
      ) : (
        <>
          <div
            aria-label={t("usage.breakdown.barLabel")}
            className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-paper-deep"
            role="img"
          >
            {all
              .filter((segment) => segment.value > 0)
              .map((segment) => (
                <span
                  className="h-full transition-[width] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
                  data-testid={`usage-breakdown-${segment.key}`}
                  key={segment.key}
                  style={{ width: `${sharePercent(segment.value, total)}%`, background: segment.color }}
                />
              ))}
          </div>
          <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
            {all.map((segment) => (
              <li className="flex items-center gap-1.5 text-caption leading-4 text-ink-soft" key={segment.key}>
                <span
                  aria-hidden="true"
                  className="size-2 shrink-0 rounded-[2px]"
                  style={{ background: segment.color }}
                />
                {t("usage.breakdown.legendItem", {
                  label: t(segment.labelKey),
                  count: formatUsageCount(segment.value, locale),
                  percent: formatUsagePercent(sharePercent(segment.value, total)),
                })}
              </li>
            ))}
          </ul>
        </>
      )}
    </PanelSurface>
  );
}
