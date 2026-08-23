import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type { AppNotificationChannelPayload } from "../../../../lib/domain";
import { invalidateAppDerivedQueries } from "../invalidateAppQueries";
import {
  channelFormComplete,
  channelFormFromChannel,
  channelLoadState,
  currentScopeIsAvailable,
  EMPTY_CHANNEL_FORM,
  parseNotificationChannelPayload,
  type ChannelFormState,
} from "./notificationChannelPayload";

/** 钉钉通知通道的读取/保存/连通性测试, 以及 secret 只写不回显的输入管理。 */
export function useNotificationChannel(appKey: string, canManage: boolean) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const queryKey = ["console", "app", appKey, "notification-channel"];
  const [form, setForm] = useState<ChannelFormState>(EMPTY_CHANNEL_FORM);
  const [hasSecretInput, setHasSecretInput] = useState(false);
  const secretInputRef = useRef<HTMLInputElement>(null);
  const channelQuery = useQuery({
    queryKey,
    queryFn: async () => parseNotificationChannelPayload(
      await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/notification-channel`),
      t("console.integration.channelInvalidResponse"),
    ),
  });
  const channel = channelQuery.data?.notification_channel ?? null;
  const availableDirectoryScopes = channelQuery.data?.available_directory_scopes ?? [];
  const loadState = channelLoadState(channelQuery.isLoading, channelQuery.isError, channel);
  const hasAuthoritativeSnapshot = loadState === "configured" || loadState === "unconfigured";

  useEffect(() => {
    if (!channelQuery.data) {
      return;
    }
    setForm(channelFormFromChannel(channelQuery.data.notification_channel));
  }, [channelQuery.data]);

  const clearSecretInput = () => {
    if (secretInputRef.current) {
      secretInputRef.current.value = "";
    }
    setHasSecretInput(false);
  };
  const saveMutation = useMutation({
    mutationFn: async () => {
      const secret = secretInputRef.current?.value ?? "";
      clearSecretInput();
      const payload = parseNotificationChannelPayload(
        await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/notification-channel`, {
          method: "PUT",
          body: {
            name: form.name.trim(),
            dingtalk_app_key: form.dingtalkAppKey.trim(),
            dingtalk_app_secret: secret,
            agent_id: form.agentId.trim(),
            directory_source_slug: form.directorySourceSlug.trim(),
            corp_id: form.corpId.trim(),
          } satisfies JsonObject,
        }),
        t("console.integration.channelInvalidResponse"),
        false,
      );
      return payload.notification_channel;
    },
    onSuccess: (notificationChannel) => {
      queryClient.setQueryData<AppNotificationChannelPayload>(queryKey, (current) => ({
        notification_channel: notificationChannel,
        available_directory_scopes: current?.available_directory_scopes ?? [],
      }));
      invalidateAppDerivedQueries(queryClient, appKey);
      toast.success(t("console.integration.channelSaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.integration.channelSaveFailed"), error.message);
    },
    onSettled: clearSecretInput,
  });
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ ok: boolean; version: number }>(`/console/api/v1/apps/${appKey}/notification-channel/test`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      toast.success(t("console.integration.channelTestSuccess", { version: payload.version }));
    },
    onError: (error: Error) => {
      toast.error(t("console.integration.channelTestFailed"), error.message);
    },
  });

  return {
    form,
    setForm,
    channel,
    channelQuery,
    availableDirectoryScopes,
    loadState,
    canWriteChannel: canManage && hasAuthoritativeSnapshot,
    secretInputRef,
    setHasSecretInput,
    saveMutation,
    testMutation,
    currentScopeIsAvailable: currentScopeIsAvailable(availableDirectoryScopes, channel),
    noAvailableScopes: hasAuthoritativeSnapshot && availableDirectoryScopes.length === 0,
    formComplete: channelFormComplete({ form, scopes: availableDirectoryScopes, channel, hasSecretInput }),
  };
}
