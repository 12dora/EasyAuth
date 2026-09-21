import { BellOff } from "lucide-react";

import { Badge } from "../../../../../components/Badge";
import { InfoTip } from "../../../../../components/InfoTip";
import { StatusBanner } from "../../../../../components/StatusBanner";
import { EmptyState } from "../../../../../components/ui/EmptyState";
import { PanelSurface } from "../../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../../i18n/messages";
import type { BadgeTone, Translator } from "../../../../../lib/status";
import { useUsageAlerts, useUsageSummary } from "../useUsageData";
import type { UsageAlertEvent } from "../usageTypes";

const KIND_LABELS: Record<string, MessageKey> = {
  threshold: "usageAlerts.kind.threshold",
  anomaly: "usageAlerts.kind.anomaly",
  enforcement: "usageAlerts.kind.enforcement",
  stream_paused: "usageAlerts.kind.stream_paused",
  stream_resumed: "usageAlerts.kind.stream_resumed",
};

const METRIC_LABELS: Record<string, MessageKey> = {
  api: "usageAlerts.metric.api",
  webhook: "usageAlerts.metric.webhook",
  stream: "usageAlerts.metric.stream",
  internal: "usageAlerts.metric.internal",
};

const STATUS_LABELS: Record<string, MessageKey> = {
  sent: "usageAlerts.status.sent",
  suppressed: "usageAlerts.status.suppressed",
  superseded: "usageAlerts.status.superseded",
  failed: "usageAlerts.status.failed",
};

const STATUS_TONES: Record<string, BadgeTone> = {
  sent: "evergreen",
  suppressed: "amber",
  superseded: "faint",
  failed: "signal",
};

/** 最近告警列表: 状态/类别徽标 + 相对时间, 顶部给出今日发送与抑制的额度口径。 */
export function UsageAlertsPanel() {
  const { t } = useI18n();
  const alertsQuery = useUsageAlerts();
  const summary = useUsageSummary();
  const alerts = alertsQuery.data?.data ?? [];
  const meta = summary.data?.alerts;

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 className="text-base font-semibold leading-tight text-ink">{t("usageAlerts.title")}</h3>
          <p className="text-body leading-5 text-ink-soft">{t("usageAlerts.description")}</p>
        </div>
        {meta ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{t("usageAlerts.sentToday", { sent: meta.sent_today, cap: meta.daily_cap })}</Badge>
            <Badge tone={meta.suppressed_today > 0 ? "amber" : "faint"}>
              {t("usageAlerts.suppressed", { count: meta.suppressed_today })}
            </Badge>
          </div>
        ) : null}
      </header>
      {alertsQuery.error ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("usageAlerts.loadFailed")}
          message={(alertsQuery.error as Error).message}
        />
      ) : alertsQuery.isLoading ? (
        <p className="text-caption leading-5 text-ink-faint" role="status">
          {t("usageAlerts.loading")}
        </p>
      ) : alerts.length === 0 ? (
        <EmptyState
          icon={<BellOff size={18} />}
          title={t("usageAlerts.empty")}
          description={t("usageAlerts.emptyDescription")}
        />
      ) : (
        <ul className="divide-y divide-ink/10">
          {alerts.map((alert) => (
            <AlertRow key={alert.id} alert={alert} />
          ))}
        </ul>
      )}
    </PanelSurface>
  );
}

function AlertRow({ alert }: { alert: UsageAlertEvent }) {
  const { t, formatDateTime } = useI18n();
  const kindKey = KIND_LABELS[alert.kind];
  const metricKey = METRIC_LABELS[alert.metric];
  const statusKey = STATUS_LABELS[alert.status];

  return (
    <li className="flex flex-wrap items-start gap-3 py-3 first:pt-0 last:pb-0">
      <div className="flex shrink-0 items-center gap-1.5">
        <Badge tone="bond">{kindKey ? t(kindKey) : alert.kind}</Badge>
        <Badge tone="faint">{metricKey ? t(metricKey) : alert.metric}</Badge>
        {alert.threshold_percent > 0 ? (
          <Badge tone="neutral">{t("usageAlerts.threshold", { percent: alert.threshold_percent })}</Badge>
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium leading-5 text-ink">{alert.title}</p>
        {alert.detail ? <p className="mt-0.5 text-caption leading-5 text-ink-soft">{alert.detail}</p> : null}
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <Badge tone={STATUS_TONES[alert.status] ?? "neutral"}>{statusKey ? t(statusKey) : alert.status}</Badge>
        {alert.status === "failed" && alert.failure_reason ? (
          <InfoTip text={t("usageAlerts.failureReason", { reason: alert.failure_reason })} />
        ) : null}
        <time className="font-mono text-micro text-ink-faint" dateTime={alert.created_at} title={formatDateTime(alert.created_at)}>
          {relativeAlertTime(t, alert.created_at, Date.now(), formatDateTime)}
        </time>
      </div>
    </li>
  );
}

/** 一天以内用相对时间, 更久远的直接给绝对时间, 避免「27 小时前」这种反直觉读数。 */
export function relativeAlertTime(
  t: Translator,
  iso: string,
  now: number,
  formatDateTime: (value: string) => string,
): string {
  const created = new Date(iso).getTime();
  if (Number.isNaN(created)) {
    return formatDateTime(iso);
  }
  const minutes = Math.floor((now - created) / 60_000);
  if (minutes < 1) {
    return t("usageAlerts.time.justNow");
  }
  if (minutes < 60) {
    return t("usageAlerts.time.minutes", { count: minutes });
  }
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? t("usageAlerts.time.hours", { count: hours }) : formatDateTime(iso);
}
