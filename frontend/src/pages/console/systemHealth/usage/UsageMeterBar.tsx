import { useI18n } from "../../../../i18n/I18nProvider";
import { SEVERITY_TEXT_CLASS, usageMeterGradient, usageMeterTrack, usageOverflowFill } from "./usageChartTheme";
import {
  formatUsageCount,
  formatUsagePercent,
  hasUsageLimit,
  usageMeterGeometry,
  usageSeverity,
  usageThresholdTicks,
} from "./usageMeterModel";

export interface UsageMeterBarProps {
  /** 今日 / 本月。 */
  scopeLabel: string;
  /** 无障碍名字里的指标名, 例如「API 计费调用」。 */
  metricLabel: string;
  used: number;
  limit: number | null;
  remaining: number | null;
  percent: number | null;
  thresholds: readonly number[];
}

/**
 * 单条用量计量条: 圆角轨道 + 渐变填充 + 告警阈值刻度。
 *
 * 填充宽度只靠 CSS 过渡, 数值一变就自己滑到新宽度; `motion-reduce` 与
 * styles/index.css 末尾的全局降级规则一起兜住「减少动态效果」。
 * 轨道底色取同一严重度色的极浅档, 于是状态读得穿整条, 而不只是填充那一截。
 */
export function UsageMeterBar({
  scopeLabel,
  metricLabel,
  used,
  limit,
  remaining,
  percent,
  thresholds,
}: UsageMeterBarProps) {
  const { t, locale } = useI18n();
  const severity = usageSeverity(percent);
  const geometry = usageMeterGeometry(percent);
  const ticks = usageThresholdTicks(thresholds);
  const percentText = percent === null ? t("common.none") : formatUsagePercent(percent);
  const usedText = formatUsageCount(used, locale);

  if (!hasUsageLimit(limit)) {
    return (
      <div className="space-y-1.5">
        <MeterHeader scopeLabel={scopeLabel} valueText={usedText} />
        <div className="h-2.5 w-full rounded-full border border-dashed border-ink/20 bg-paper-deep" />
        <p className="text-caption leading-4 text-ink-faint">{t("usage.meter.noLimit")}</p>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <MeterHeader
        scopeLabel={scopeLabel}
        valueText={t("usage.meter.usedOfLimit", { used: usedText, limit: formatUsageCount(limit, locale) })}
      />
      <div className="relative">
        <div className="h-2.5 w-full overflow-hidden rounded-full" style={{ background: usageMeterTrack(severity) }}>
          <div
            aria-label={t("usage.meter.progressLabel", {
              metric: metricLabel,
              scope: scopeLabel,
              percent: percentText,
            })}
            aria-valuemax={limit}
            aria-valuemin={0}
            aria-valuenow={used}
            aria-valuetext={percentText}
            className="h-full rounded-r-full transition-[width] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
            role="progressbar"
            style={{
              width: `${geometry.fillPercent}%`,
              // 超限时整条换成 45° 斜纹: 色相之外再给一层不依赖颜色的区分。
              backgroundImage: geometry.hasOverflow ? usageOverflowFill() : usageMeterGradient(severity),
            }}
          />
        </div>
        <div aria-label={t("usage.meter.thresholdLegend")} className="pointer-events-none absolute inset-0" role="group">
          {ticks.map((tick) => (
            <span
              className="pointer-events-auto absolute top-1/2 h-3.5 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink/30"
              data-testid="usage-threshold-tick"
              key={tick}
              style={{ left: `${tick}%` }}
              title={t("usage.meter.thresholdTick", { percent: tick })}
            />
          ))}
        </div>
      </div>
      <div className="flex items-baseline justify-between gap-2 text-caption leading-4">
        <span className="text-ink-faint">
          {remaining === null
            ? t("usage.meter.noLimit")
            : t("usage.meter.remaining", { remaining: formatUsageCount(Math.max(remaining, 0), locale) })}
        </span>
        <span className={`font-mono font-semibold ${SEVERITY_TEXT_CLASS[severity]}`}>
          {geometry.hasOverflow
            ? t("usage.meter.overflow", { percent: formatUsagePercent(geometry.overflowPercent) })
            : percentText}
        </span>
      </div>
    </div>
  );
}

function MeterHeader({ scopeLabel, valueText }: { scopeLabel: string; valueText: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-caption font-medium leading-4 text-ink-soft">{scopeLabel}</span>
      <span className="font-mono text-caption leading-4 text-ink">{valueText}</span>
    </div>
  );
}
