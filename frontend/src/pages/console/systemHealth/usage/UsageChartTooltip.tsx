import { useI18n } from "../../../../i18n/I18nProvider";
import { USAGE_ALL_SERIES, USAGE_SERIES_LABEL_KEYS, bucketTotal, type UsageChartRow } from "./usageChartModel";
import { USAGE_SERIES_COLOR, USAGE_SINGLE_SERIES_COLOR } from "./usageChartTheme";
import { formatUsageCount } from "./usageMeterModel";

/** 序列在悬浮卡里的色键; 小图里的单序列统一走第 1 位标识色。 */
const TOOLTIP_KEY_COLOR: Record<string, string> = {
  api_billed: USAGE_SERIES_COLOR.api_billed,
  api_unbilled: USAGE_SERIES_COLOR.api_unbilled,
  internal: USAGE_SERIES_COLOR.internal,
  webhook: USAGE_SINGLE_SERIES_COLOR,
  stream: USAGE_SINGLE_SERIES_COLOR,
  blocked: USAGE_SERIES_COLOR.blocked,
};

/**
 * recharts 传给 `<Tooltip content={...} />` 的形状; 只取需要的字段,
 * 这样悬浮卡本身不依赖 recharts, 可以单独渲染与测试。
 */
export interface UsageChartTooltipProps {
  active?: boolean;
  payload?: readonly { payload?: UsageChartRow }[];
}

/**
 * 一张悬浮卡列出该时间桶的**全部**序列与合计 —— 指针落在哪张图上都读到同一份完整数据,
 * 不需要为了看 Webhook 再去瞄另一张图。数值是强调项, 序列名次之。
 */
export function UsageChartTooltip({ active, payload }: UsageChartTooltipProps) {
  const { t, locale } = useI18n();
  const row = payload?.[0]?.payload;
  if (!active || !row) {
    return null;
  }

  return (
    <div className="paper-card min-w-44 px-3 py-2 shadow-lg">
      <p className="mb-1.5 font-mono text-micro uppercase tracking-caps text-ink-faint">{row.tooltipLabel}</p>
      <ul className="space-y-0.5">
        {USAGE_ALL_SERIES.map((key) => (
          <li className="flex items-center justify-between gap-4" key={key}>
            <span className="flex items-center gap-1.5 text-caption leading-4 text-ink-soft">
              <span
                aria-hidden="true"
                className="inline-block h-0.5 w-3 shrink-0 rounded-full"
                style={{ background: TOOLTIP_KEY_COLOR[key] }}
              />
              {t(USAGE_SERIES_LABEL_KEYS[key])}
            </span>
            <span className="font-mono text-caption font-semibold leading-4 text-ink">
              {formatUsageCount(row[key], locale)}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 flex items-center justify-between gap-4 border-t border-ink/10 pt-1.5">
        <span className="text-caption leading-4 text-ink-soft">{t("usage.trend.tooltipTotal")}</span>
        <span className="font-mono text-caption font-semibold leading-4 text-ink">
          {formatUsageCount(bucketTotal(row), locale)}
        </span>
      </p>
    </div>
  );
}
