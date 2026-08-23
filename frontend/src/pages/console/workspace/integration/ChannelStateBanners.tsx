import { RefreshCcw } from "lucide-react";

import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppNotificationChannelPayload } from "../../../../lib/domain";
import type { ChannelLoadState } from "./notificationChannelPayload";

/** 通道加载态与目录范围状态的提示条组合。 */
export function ChannelStateBanners({
  loadState,
  channel,
  currentScopeIsAvailable,
  noAvailableScopes,
  loadError,
  isRefetching,
  onRetry,
}: {
  loadState: ChannelLoadState;
  channel: AppNotificationChannelPayload["notification_channel"];
  currentScopeIsAvailable: boolean;
  noAvailableScopes: boolean;
  loadError: Error | null;
  isRefetching: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();

  return (
    <>
      {loadState === "loading" ? <StatusBanner title={t("console.integration.channelLoading")} /> : null}
      {loadState === "error" ? (
        <div className="space-y-3">
          <StatusBanner
            live="alert"
            tone="signal"
            title={t("console.integration.channelLoadFailed")}
            message={loadError?.message ?? ""}
          />
          <Button type="button" icon={<RefreshCcw size={15} />} loading={isRefetching} onClick={onRetry}>
            {t("common.retry")}
          </Button>
        </div>
      ) : null}
      {loadState === "unconfigured" ? (
        <StatusBanner
          live="status"
          tone="amber"
          title={t("console.integration.channelNotConfigured")}
          message={t("console.integration.channelEmptyDescription")}
        />
      ) : null}
      {loadState === "configured" ? <DirectoryScopeRow channel={channel} isAvailable={currentScopeIsAvailable} /> : null}
      {loadState === "configured" && !currentScopeIsAvailable ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("console.integration.currentScopeUnavailable")}
          message={t("console.integration.currentScopeUnavailableDescription")}
        />
      ) : null}
      {noAvailableScopes ? (
        <StatusBanner
          live="status"
          tone="amber"
          title={t("console.integration.noAvailableScopes")}
          message={t("console.integration.noAvailableScopesDescription")}
        />
      ) : null}
    </>
  );
}

function DirectoryScopeRow({
  channel,
  isAvailable,
}: {
  channel: AppNotificationChannelPayload["notification_channel"];
  isAvailable: boolean;
}) {
  const { t } = useI18n();

  return (
    <div className={`flex flex-wrap items-center justify-between gap-2 border px-3 py-2 ${isAvailable ? "border-bond/25 bg-bond/5" : "border-signal/30 bg-signal/8"}`}>
      <span className={`text-label font-semibold uppercase tracking-caps-wide ${isAvailable ? "text-bond" : "text-signal"}`}>
        {t("console.integration.directoryScope")}
      </span>
      <code className="text-xs text-ink">
        {channel?.directory_source_slug} / {channel?.corp_id}
      </code>
    </div>
  );
}
