import { RefreshCcw } from "lucide-react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { WebhookRotateDialog, WebhookSecretDialog, WebhookTabForm } from "./WebhookTabForm";
import { useWebhookTab } from "./useWebhookTab";
import type { WebhookConfigState } from "./webhookConfig";

export function WebhookTab({ appKey }: { appKey: string }) {
  const tab = useWebhookTab(appKey);

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="space-y-5">
        <WebhookTabHeader configState={tab.configState} />
        {tab.configState.status === "error" ? (
          <div className="space-y-3">
            <StatusBanner live="alert" tone="signal" title={tab.t("webhook.loadFailed")} message={tab.configState.error.message} />
            <Button
              type="button"
              icon={<RefreshCcw size={15} />}
              loading={tab.configQuery.isFetching}
              onClick={() => void tab.configQuery.refetch()}
            >
              {tab.t("common.retry")}
            </Button>
          </div>
        ) : null}
        {tab.configState.status === "unconfigured" ? (
          <StatusBanner live="status" tone="amber" title={tab.t("webhook.notConfigured")} />
        ) : null}
        <WebhookTabForm tab={tab} />
      </PanelSurface>
      <WebhookRotateDialog tab={tab} />
      <WebhookSecretDialog tab={tab} />
    </section>
  );
}

function WebhookTabHeader({ configState }: { configState: WebhookConfigState }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("webhook.heading")}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("webhook.description")}</p>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">{t("webhook.secretLabel")}</span>
        {configState.status === "loading" ? <Badge>{t("common.loading")}</Badge> : null}
        {configState.status === "error" ? <Badge tone="signal">{t("webhook.loadFailed")}</Badge> : null}
        {configState.status === "unconfigured" ? <Badge tone="amber">{t("webhook.secretMissing")}</Badge> : null}
        {configState.status === "configured" ? (
          <Badge tone={configState.config.secret_configured ? "evergreen" : "amber"}>
            {configState.config.secret_configured ? t("webhook.secretConfigured") : t("webhook.secretMissing")}
          </Badge>
        ) : null}
      </div>
    </div>
  );
}
