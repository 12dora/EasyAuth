import { RefreshCw, Trash2 } from "lucide-react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { ConnectorInstanceItem } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { formatDateTime } from "../../../../lib/status";
import { ConnectorInstanceForm } from "./ConnectorInstanceForm";
import { RUN_STATUS_TONES, runStatusLabel } from "./connectorFormat";
import type { ConnectorInstanceFormController } from "./useConnectorInstanceForm";

export function ConnectorInstancePanel({
  controller,
}: {
  controller: ConnectorInstanceFormController;
}) {
  const { t } = useI18n();
  const { instance } = controller.selection;

  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <h2 className="text-base font-semibold text-ink">
            {t("console.connector.heading")}
          </h2>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">
            {t("console.connector.description")}
          </p>
        </div>
        {instance ? <InstanceStatusBadges t={t} instance={instance} /> : null}
      </div>
      <ConnectorStatusBanners controller={controller} />
      {instance ? (
        <ConnectorInstanceActions controller={controller} instance={instance} />
      ) : null}
      <ConnectorInstanceForm controller={controller} />
      <p className="text-xs leading-5 text-ink-faint">
        {t("console.connector.superuserHint")}
      </p>
    </PanelSurface>
  );
}

function ConnectorStatusBanners({
  controller,
}: {
  controller: ConnectorInstanceFormController;
}) {
  const { t } = useI18n();
  const { connectorsQuery } = controller;
  const { instance } = controller.selection;

  return (
    <>
      {connectorsQuery.error ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("console.connector.loadFailed")}
          message={(connectorsQuery.error as Error).message}
        />
      ) : null}
      {instance?.consecutive_failures ? (
        <StatusBanner
          live="status"
          tone={instance.consecutive_failures >= 3 ? "signal" : "amber"}
          title={t("console.connector.consecutiveFailures", {
            count: String(instance.consecutive_failures),
          })}
          message={instance.last_error}
        />
      ) : null}
      {!connectorsQuery.isLoading && !connectorsQuery.error && !instance ? (
        <StatusBanner
          live="status"
          tone="amber"
          title={t("console.connector.notConfigured")}
        />
      ) : null}
    </>
  );
}

function ConnectorInstanceActions({
  controller,
  instance,
}: {
  controller: ConnectorInstanceFormController;
  instance: ConnectorInstanceItem;
}) {
  const { t } = useI18n();
  const { canManage, drafts, mutations } = controller;
  const { reconcileMutation } = mutations;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="text-xs leading-5 text-ink-faint">
        {t("console.connector.updatedMeta", {
          user: instance.updated_by || "-",
          time: formatDateTime(instance.updated_at),
        })}
      </span>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          icon={<RefreshCw size={14} />}
          loading={reconcileMutation.isPending}
          disabled={reconcileMutation.isPending || !instance.enabled || !canManage}
          onClick={() => reconcileMutation.mutate()}
        >
          {t("console.connector.reconcileNow")}
        </Button>
        <Button
          type="button"
          variant="ghost-danger"
          icon={<Trash2 size={14} />}
          disabled={!canManage}
          onClick={() => drafts.setDeleteConfirmOpen(true)}
        >
          {t("console.connector.deleteInstance")}
        </Button>
      </div>
    </div>
  );
}

function InstanceStatusBadges({
  t,
  instance,
}: {
  t: Translator;
  instance: ConnectorInstanceItem;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge tone={instance.enabled ? "evergreen" : "neutral"}>
        {instance.enabled ? t("common.enabled") : t("common.disabled")}
      </Badge>
      <span className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">
        {t("console.connector.statusLabel")}
      </span>
      {instance.last_reconcile_at ? (
        <>
          <Badge tone={RUN_STATUS_TONES[instance.last_status] ?? "neutral"}>
            {runStatusLabel(t, instance.last_status)}
          </Badge>
          <span className="text-xs text-ink-faint">
            {formatDateTime(instance.last_reconcile_at)}
          </span>
        </>
      ) : (
        <Badge tone="neutral">{t("console.connector.status.never")}</Badge>
      )}
    </div>
  );
}
