import { PlugZap } from "lucide-react";
import type { FormEvent } from "react";

import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import { ChannelStateBadges } from "./ChannelStateBadges";
import { ChannelStateBanners } from "./ChannelStateBanners";
import { NotificationChannelForm } from "./NotificationChannelForm";
import { useNotificationChannel } from "./useNotificationChannel";

export function NotificationChannelPanel({ appKey, canManage }: { appKey: string; canManage: boolean }) {
  const { t } = useI18n();
  const channelState = useNotificationChannel(appKey, canManage);
  const { channel, channelQuery, loadState, canWriteChannel, currentScopeIsAvailable, saveMutation } = channelState;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canWriteChannel) {
      saveMutation.mutate();
    }
  };

  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <PlugZap size={17} aria-hidden="true" />
            <h3 className="text-sm font-semibold text-ink">{t("console.integration.channelHeading")}</h3>
          </div>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("console.integration.channelDescription")}</p>
        </div>
        <ChannelStateBadges loadState={loadState} channel={channel} />
      </div>
      <ChannelStateBanners
        loadState={loadState}
        channel={channel}
        currentScopeIsAvailable={currentScopeIsAvailable}
        noAvailableScopes={channelState.noAvailableScopes}
        loadError={channelQuery.error}
        isRefetching={channelQuery.isFetching}
        onRetry={() => void channelQuery.refetch()}
      />
      <NotificationChannelForm
        form={channelState.form}
        setForm={channelState.setForm}
        channel={channel}
        availableDirectoryScopes={channelState.availableDirectoryScopes}
        currentScopeIsAvailable={currentScopeIsAvailable}
        noAvailableScopes={channelState.noAvailableScopes}
        canWriteChannel={canWriteChannel}
        isLoading={channelQuery.isLoading}
        isSaving={saveMutation.isPending}
        isTesting={channelState.testMutation.isPending}
        formComplete={channelState.formComplete}
        secretInputRef={channelState.secretInputRef}
        onSecretInput={channelState.setHasSecretInput}
        onSubmit={submit}
        onTest={() => channelState.testMutation.mutate()}
      />
    </PanelSurface>
  );
}
