import { Badge } from "../../../../components/Badge";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppNotificationChannelPayload } from "../../../../lib/domain";
import type { ChannelLoadState } from "./notificationChannelPayload";

export function ChannelStateBadges({
  loadState,
  channel,
}: {
  loadState: ChannelLoadState;
  channel: AppNotificationChannelPayload["notification_channel"];
}) {
  return (
    <div className="flex items-center gap-2">
      {loadState === "configured" ? <ConfiguredChannelBadges channel={channel} /> : <PendingChannelBadge loadState={loadState} />}
    </div>
  );
}

function ConfiguredChannelBadges({ channel }: { channel: AppNotificationChannelPayload["notification_channel"] }) {
  const { t } = useI18n();

  return (
    <>
      <Badge tone="neutral">v{channel?.version}</Badge>
      <Badge tone={channel?.app_secret_configured ? "evergreen" : "amber"}>
        {channel?.app_secret_configured ? t("console.integration.secretConfigured") : t("console.integration.secretMissing")}
      </Badge>
    </>
  );
}

function PendingChannelBadge({ loadState }: { loadState: ChannelLoadState }) {
  const { t } = useI18n();

  if (loadState === "loading") {
    return <Badge>{t("common.loading")}</Badge>;
  }
  if (loadState === "error") {
    return <Badge tone="signal">{t("console.integration.channelLoadFailed")}</Badge>;
  }
  return <Badge tone="amber">{t("console.integration.channelNotConfigured")}</Badge>;
}
