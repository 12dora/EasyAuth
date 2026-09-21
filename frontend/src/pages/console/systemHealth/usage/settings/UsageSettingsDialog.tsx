import { Check, RefreshCcw } from "lucide-react";
import { useRef } from "react";

import { Button } from "../../../../../components/Button";
import { Dialog } from "../../../../../components/Dialog";
import { MutationErrorBanner, StatusBanner } from "../../../../../components/StatusBanner";
import { ConfirmDialog } from "../../../../../components/ui/ConfirmDialog";
import { PageState } from "../../../../../components/ui/PageState";
import { useRovingTabs } from "../../../../../components/useRovingTabs";
import { useI18n } from "../../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../../i18n/messages";
import { cn } from "../../../../../lib/cn";
import { useUsageSummary } from "../useUsageData";
import type { UsageAlertsSummary, UsageMetricKey, UsageMetricSummary } from "../usageTypes";
import { AlertsSettingsSection, type AlertsReadiness } from "./AlertsSettingsSection";
import { MetricSettingsSection, type MetricUsageSnapshot } from "./MetricSettingsSection";
import { USAGE_SECTIONS, type UsageSettingsSection } from "./usageSettingsDocument";
import { useUsageSettingsForm, type UsageSettingsController } from "./useUsageSettingsForm";

const SECTION_LABELS: Record<UsageSettingsSection, MessageKey> = {
  api: "usageSettings.section.api",
  webhook: "usageSettings.section.webhook",
  stream: "usageSettings.section.stream",
  alerts: "usageSettings.section.alerts",
};

export function UsageSettingsDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const controller = useUsageSettingsForm(onClose);
  const { saveMutation } = controller;
  // 二次确认弹窗打开时锁住外层的 Esc/关闭, 否则一次 Esc 会同时被两层接住。
  const closeLocked = saveMutation.isPending || controller.pendingClose || controller.pendingPolicy !== null;

  return (
    <>
      <Dialog
        title={t("usageSettings.title")}
        eyebrow={t("usageSettings.eyebrow")}
        size="xl"
        closeDisabled={closeLocked}
        onClose={controller.requestClose}
        footer={
          <>
            {saveMutation.isSuccess && !controller.dirty ? (
              <span className="mr-auto inline-flex items-center gap-1.5 text-caption font-medium text-evergreen" role="status">
                <Check size={14} aria-hidden="true" />
                {t("usageSettings.saved")}
              </span>
            ) : null}
            <Button type="button" onClick={controller.requestClose} disabled={saveMutation.isPending}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="primary"
              loading={saveMutation.isPending}
              disabled={controller.form === null}
              onClick={controller.submit}
            >
              {t("usageSettings.save")}
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-5 md:flex-row">
          <SectionNav controller={controller} />
          <div className="min-w-0 flex-1 space-y-4">
            <DialogNotices controller={controller} />
            <DialogBody controller={controller} />
          </div>
        </div>
      </Dialog>
      {controller.pendingClose ? (
        <ConfirmDialog
          title={t("usageSettings.dirty.title")}
          message={t("usageSettings.dirty.message")}
          confirmLabel={t("usageSettings.dirty.confirm")}
          onConfirm={controller.confirmClose}
          onClose={controller.cancelClose}
        />
      ) : null}
      {controller.pendingPolicy !== null ? (
        <ConfirmDialog
          title={t("usageSettings.blockAll.title")}
          message={t("usageSettings.blockAll.message")}
          confirmLabel={t("usageSettings.blockAll.confirm")}
          onConfirm={controller.confirmPolicy}
          onClose={controller.cancelPolicy}
        />
      ) : null}
    </>
  );
}

function SectionNav({ controller }: { controller: UsageSettingsController }) {
  const { t, formatDateTime } = useI18n();
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const onKeyDown = useRovingTabs({
    activeKey: controller.section,
    items: USAGE_SECTIONS,
    refs: tabRefs,
    onActivate: controller.setSection,
  });
  const { payload } = controller;

  return (
    <div className="md:w-44 md:shrink-0">
      <div
        role="tablist"
        aria-label={t("usageSettings.nav")}
        className="flex gap-1 overflow-x-auto rounded-[3px] border border-ink/12 bg-paper-deep/50 p-1 md:flex-col md:overflow-visible"
        onKeyDown={onKeyDown}
      >
        {USAGE_SECTIONS.map((key, index) => (
          <button
            key={key}
            ref={(node) => {
              tabRefs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`usage-settings-tab-${key}`}
            aria-controls={`usage-settings-panel-${key}`}
            aria-selected={key === controller.section}
            tabIndex={key === controller.section ? 0 : -1}
            className={cn(
              "h-8 shrink-0 rounded-[2px] px-3 text-caption font-medium transition-colors duration-150 motion-reduce:transition-none md:text-left",
              key === controller.section ? "bg-paper text-ink" : "text-ink-soft hover:text-ink",
            )}
            onClick={() => controller.setSection(key)}
          >
            {t(SECTION_LABELS[key])}
          </button>
        ))}
      </div>
      {payload ? (
        <p className="mt-2 hidden text-xs leading-5 text-ink-faint md:block">
          {payload.updated_by
            ? t("usageSettings.meta", {
                version: payload.version,
                updatedAt: formatDateTime(payload.updated_at),
                updatedBy: payload.updated_by,
              })
            : t("usageSettings.metaNoActor", {
                version: payload.version,
                updatedAt: formatDateTime(payload.updated_at),
              })}
        </p>
      ) : null}
    </div>
  );
}

function DialogNotices({ controller }: { controller: UsageSettingsController }) {
  const { t } = useI18n();
  const errorCount = Object.keys(controller.errors).length;

  return (
    <>
      {controller.conflict ? (
        <ReloadNotice
          title={t("usageSettings.conflict.title")}
          message={t("usageSettings.conflict.message")}
          loading={controller.query.isFetching}
          onReload={controller.reload}
        />
      ) : controller.staleRemote ? (
        <ReloadNotice
          title={t("usageSettings.stale.title")}
          message={t("usageSettings.stale.message")}
          loading={controller.query.isFetching}
          onReload={controller.reload}
        />
      ) : (
        <MutationErrorBanner title={t("usageSettings.saveFailed")} error={controller.saveMutation.error} />
      )}
      {errorCount > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("usageSettings.validationFailed", { count: errorCount })} />
      ) : null}
    </>
  );
}

function ReloadNotice({
  title,
  message,
  loading,
  onReload,
}: {
  title: string;
  message: string;
  loading: boolean;
  onReload: () => void;
}) {
  const { t } = useI18n();

  return (
    <div className="flex flex-wrap items-start gap-3 rounded-[3px] border border-amber/30 bg-amber/8 px-4 py-3 text-amber" role="alert">
      <div className="min-w-0 flex-1">
        <strong className="block text-sm font-semibold leading-5">{title}</strong>
        <p className="mt-1 text-sm leading-5 text-ink-soft">{message}</p>
      </div>
      <Button type="button" size="sm" icon={<RefreshCcw size={14} />} loading={loading} onClick={onReload}>
        {t("usageSettings.conflict.reload")}
      </Button>
    </div>
  );
}

function DialogBody({ controller }: { controller: UsageSettingsController }) {
  const { t } = useI18n();
  const summary = useUsageSummary();
  const { form, query, section } = controller;

  if (form === null) {
    return query.error ? (
      <PageState
        tone="signal"
        title={t("usageSettings.loadFailed")}
        description={(query.error as Error).message}
        action={
          <Button icon={<RefreshCcw size={16} />} loading={query.isFetching} onClick={() => void query.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    ) : (
      <PageState title={t("usageSettings.loading")} description={t("usageSettings.loadingDescription")} />
    );
  }

  return (
    <div
      key={section}
      role="tabpanel"
      id={`usage-settings-panel-${section}`}
      aria-labelledby={`usage-settings-tab-${section}`}
      className="route-transition"
    >
      {section === "alerts" ? (
        <AlertsSettingsSection
          form={form.alerts}
          errors={controller.errors}
          readiness={alertsReadiness(summary.data?.alerts)}
          onChange={controller.updateAlerts}
        />
      ) : (
        <MetricSettingsSection
          metric={section}
          form={form[section]}
          errors={controller.errors}
          usage={metricUsage(summary.data?.metrics, section)}
          onChange={(updater) => controller.updateMetric(section, updater)}
          onSelectPolicy={(policy) => controller.selectPolicy(section, policy)}
        />
      )}
    </div>
  );
}

/** 概览里当前指标的今日/本月已用量; 概览没加载出来时预览条显示「暂无用量数据」。 */
function metricUsage(metrics: UsageMetricSummary[] | undefined, metric: UsageMetricKey): MetricUsageSnapshot | null {
  const entry = metrics?.find((item) => item.metric === metric);
  return entry ? { today: entry.today.used, month: entry.month.used } : null;
}

/** 发送方可用性与接收人规模只读展示, 概览不可用时告警分区给出说明。 */
function alertsReadiness(alerts: UsageAlertsSummary | undefined): AlertsReadiness | null {
  if (!alerts) {
    return null;
  }
  return {
    senderReady: alerts.sender_ready,
    senderProblem: alerts.sender_problem,
    recipientCount: alerts.recipient_count,
  };
}
