import { useI18n } from "../../../../../i18n/I18nProvider";
import { SEVERITY_TEXT_CLASS, usageMeterGradient, usageMeterTrack, usageOverflowFill } from "../usageChartTheme";
import {
  formatUsageCount,
  formatUsagePercent,
  hasUsageLimit,
  usageMeterGeometry,
  usageSeverity,
  usageThresholdTicks,
} from "../usageMeterModel";

/**
 * 设置弹窗里的迷你预览条: 用当前用量对照正在输入的上限。
 *
 * 配色、严重度分档、刻度与溢出斜纹全部复用页面计量条的同一套模型,
 * 所以弹窗里看到的那一截和卡片上的大条读数一致; 宽度过渡由 CSS 负责,
 * prefers-reduced-motion 下直接跳变。
 */
export function QuotaPreviewBar({
  label,
  used,
  limit,
  thresholds,
}: {
  label: string;
  used: number | null;
  limit: number | null;
  thresholds: readonly number[];
}) {
  const { t, locale } = useI18n();
  const percent = used !== null && hasUsageLimit(limit) ? (used / limit) * 100 : null;
  const severity = usageSeverity(percent);
  const geometry = usageMeterGeometry(percent);

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-caption leading-4 text-ink-soft">{label}</span>
        <span className={`font-mono text-caption tabular-nums leading-4 ${SEVERITY_TEXT_CLASS[severity]}`}>
          {used === null
            ? t("usageSettings.preview.noData")
            : percent === null
              ? t("usageSettings.preview.unlimited", { used: formatUsageCount(used, locale) })
              : t("usageSettings.preview.used", {
                  used: formatUsageCount(used, locale),
                  limit: formatUsageCount(limit ?? 0, locale),
                  percent: formatUsagePercent(percent),
                })}
        </span>
      </div>
      <div className="relative h-1.5 w-full overflow-hidden rounded-full" style={{ background: usageMeterTrack(severity) }}>
        <div
          className="h-full rounded-r-full transition-[width] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] motion-reduce:transition-none"
          style={{
            width: `${geometry.fillPercent}%`,
            backgroundImage: geometry.hasOverflow ? usageOverflowFill() : usageMeterGradient(severity),
          }}
        />
        {hasUsageLimit(limit)
          ? usageThresholdTicks(thresholds).map((tick) => (
              <span
                key={tick}
                aria-hidden="true"
                className="absolute top-0 h-full w-0.5 -translate-x-1/2 rounded-full bg-ink/30"
                style={{ left: `${tick}%` }}
              />
            ))
          : null}
      </div>
      {geometry.hasOverflow ? (
        <p className="text-xs leading-5 text-signal">{t("usageSettings.preview.exceeded")}</p>
      ) : null}
    </div>
  );
}
