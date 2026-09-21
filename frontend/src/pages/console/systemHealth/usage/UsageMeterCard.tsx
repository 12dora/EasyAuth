import { Badge } from "../../../../components/Badge";
import { InfoTip } from "../../../../components/InfoTip";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import UsageSettingsButton from "./settings/UsageSettingsButton";
import { UsageCountUp } from "./UsageCountUp";
import { UsageMeterBar } from "./UsageMeterBar";
import {
  enforcementTone,
  formatUsageCount,
  hasUsageLimit,
  isEnforcementActive,
} from "./usageMeterModel";
import type {
  UsageEnforcementStateKey,
  UsageMetricKey,
  UsageMetricSummary,
  UsageOverLimitPolicy,
} from "./usageTypes";

const METRIC_LABEL_KEYS: Record<UsageMetricKey, MessageKey> = {
  api: "usage.metric.api",
  webhook: "usage.metric.webhook",
  stream: "usage.metric.stream",
};

const METRIC_HINT_KEYS: Record<UsageMetricKey, MessageKey> = {
  api: "usage.metric.api.hint",
  webhook: "usage.metric.webhook.hint",
  stream: "usage.metric.stream.hint",
};

const POLICY_KEYS: Record<UsageOverLimitPolicy, MessageKey> = {
  alert_only: "usage.policy.alert_only",
  degrade: "usage.policy.degrade",
  throttle: "usage.policy.throttle",
  block_all: "usage.policy.block_all",
  pause_stream: "usage.policy.pause_stream",
};

const ENFORCEMENT_KEYS: Record<UsageEnforcementStateKey, MessageKey> = {
  normal: "usage.enforcement.normal",
  degraded_p2: "usage.enforcement.degraded_p2",
  degraded_p1: "usage.enforcement.degraded_p1",
  throttled: "usage.enforcement.throttled",
  blocked: "usage.enforcement.blocked",
  stream_paused: "usage.enforcement.stream_paused",
};

/** 单个指标的用量卡: 大数字 + 今日/本月两条计量条 + 策略与生效状态。 */
export function UsageMeterCard({ metric }: { metric: UsageMetricSummary }) {
  const { t, locale } = useI18n();
  const metricLabel = t(METRIC_LABEL_KEYS[metric.metric]);
  const hasQuota = hasUsageLimit(metric.today.cap) || hasUsageLimit(metric.month.quota);

  return (
    <PanelSurface padding="lg" className="flex h-full flex-col gap-4">
      <header className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-1">
          <h3 className="text-sm font-semibold leading-tight text-ink">{metricLabel}</h3>
          <InfoTip text={t(METRIC_HINT_KEYS[metric.metric])} />
        </div>
        <EnforcementPill enforcement={metric.enforcement} />
      </header>

      <div className="flex items-end justify-between gap-3">
        <div>
          <UsageCountUp className="block text-title font-semibold leading-none text-ink" value={metric.today.used} />
          <p className="mt-1.5 text-caption leading-4 text-ink-faint">{t("usage.meter.hero")}</p>
        </div>
        <div className="text-right text-caption leading-4 text-ink-faint">
          <p>{t("usage.meter.lastHour", { count: formatUsageCount(metric.last_hour, locale) })}</p>
          {metric.blocked_today > 0 ? (
            <p className="mt-1 font-semibold text-signal">
              {t("usage.meter.blockedToday", { count: formatUsageCount(metric.blocked_today, locale) })}
            </p>
          ) : null}
        </div>
      </div>

      {hasQuota ? (
        <div className="flex flex-1 flex-col gap-3">
          <UsageMeterBar
            limit={metric.today.cap}
            metricLabel={metricLabel}
            percent={metric.today.percent}
            remaining={metric.today.remaining}
            scopeLabel={t("usage.meter.today")}
            thresholds={metric.thresholds_percent}
            used={metric.today.used}
          />
          <UsageMeterBar
            limit={metric.month.quota}
            metricLabel={metricLabel}
            percent={metric.month.percent}
            remaining={metric.month.remaining}
            scopeLabel={t("usage.meter.month")}
            thresholds={metric.thresholds_percent}
            used={metric.month.used}
          />
          <UsageMeterHints metric={metric} />
        </div>
      ) : (
        <NoQuotaState />
      )}

      <footer className="mt-auto flex items-center gap-2 border-t border-ink/10 pt-3">
        <span className="text-micro uppercase tracking-caps text-ink-faint">{t("usage.policy.label")}</span>
        <Badge tone="neutral">{t(POLICY_KEYS[metric.policy])}</Badge>
      </footer>
    </PanelSurface>
  );
}

/** 「下一档告警」与「月底预计」两行提示: 这是用户真正想读的「还能用多久」。 */
function UsageMeterHints({ metric }: { metric: UsageMetricSummary }) {
  const { t, locale } = useI18n();
  const next = metric.next_threshold;

  return (
    <div className="space-y-1 text-caption leading-5">
      <p className="text-ink-soft">
        {next === null
          ? t("usage.meter.noNextThreshold")
          : t(next.scope === "day" ? "usage.meter.nextThresholdDay" : "usage.meter.nextThresholdMonth", {
              remaining: formatUsageCount(next.remaining, locale),
              percent: next.percent,
            })}
      </p>
      {metric.month.projected === null ? null : (
        <p className="text-ink-faint">
          {t("usage.meter.projected", { count: formatUsageCount(metric.month.projected, locale) })}
        </p>
      )}
    </div>
  );
}

function NoQuotaState() {
  const { t } = useI18n();
  return (
    <div className="flex flex-1 flex-col items-start gap-2 rounded-[3px] border border-dashed border-ink/20 bg-paper-deep px-3 py-3">
      <p className="text-caption font-semibold leading-5 text-ink">{t("usage.meter.noQuotaTitle")}</p>
      <p className="text-caption leading-5 text-ink-faint">{t("usage.meter.noQuotaDescription")}</p>
      <UsageSettingsButton variant="inline" />
    </div>
  );
}

/**
 * 生效状态药丸。非正常状态下小圆点做一次轻脉冲 —— 只是提示「还在生效中」,
 * 不抢卡片里数字的注意力; `motion-reduce` 下直接不画这层光晕。
 */
function EnforcementPill({ enforcement }: { enforcement: UsageMetricSummary["enforcement"] }) {
  const { t, formatDateTime } = useI18n();
  const active = isEnforcementActive(enforcement.state);
  const reason =
    enforcement.reason === "daily_cap"
      ? t("usage.enforcement.reasonDay")
      : enforcement.reason === "monthly_quota"
        ? t("usage.enforcement.reasonMonth")
        : "";
  const since = enforcement.since ? t("usage.enforcement.since", { time: formatDateTime(enforcement.since) }) : "";

  return (
    <span className="shrink-0" title={[reason, since].filter(Boolean).join(" · ")}>
      <Badge tone={enforcementTone(enforcement.state)}>
        <span className="relative inline-flex size-1.5 shrink-0" aria-hidden="true">
          {active ? (
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-current opacity-60 motion-reduce:hidden" />
          ) : null}
          <span className="relative inline-flex size-1.5 rounded-full bg-current" />
        </span>
        {t(ENFORCEMENT_KEYS[enforcement.state])}
      </Badge>
    </span>
  );
}
