import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import { deliveryStateLabel } from "../../../../lib/status";
import {
  parseWebhookConfigPayload,
  type WebhookConfigState,
  type WebhookTarget,
} from "./webhookConfig";

interface WebhookTestResult {
  delivery_id: string;
  status: string;
}

export function useWebhookTab(appKey: string) {
  const { t } = useI18n();
  const queryKey = ["console", "app", appKey, "webhook-config"];
  const [enabled, setEnabled] = useState(true);
  const [urls, setUrls] = useState<Record<WebhookTarget, string>>({
    approval_callback_url: "",
    handover_url: "",
    onboard_url: "",
    events_url: "",
  });
  const [rotateConfirmOpen, setRotateConfirmOpen] = useState(false);
  const [oneTimeSecret, setOneTimeSecret] = useState("");

  const configQuery = useQuery({
    queryKey,
    queryFn: async () => {
      const payload = await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/webhook-config`);
      return parseWebhookConfigPayload(payload, t("webhook.loadFailed"));
    },
    enabled: Boolean(appKey),
  });
  const configState: WebhookConfigState = (() => {
    if (configQuery.error) {
      return { status: "error", error: configQuery.error as Error };
    }
    if (configQuery.isLoading || !configQuery.data) {
      return { status: "loading" };
    }
    if (configQuery.data.webhook_config === null) {
      return { status: "unconfigured" };
    }
    return { status: "configured", config: configQuery.data.webhook_config };
  })();
  const config = configState.status === "configured" ? configState.config : null;
  const canWrite = configState.status === "configured" || configState.status === "unconfigured";

  useEffect(() => {
    if (!canWrite) {
      return;
    }
    setEnabled(config?.enabled ?? true);
    setUrls({
      approval_callback_url: config?.approval_callback_url ?? "",
      handover_url: config?.handover_url ?? "",
      onboard_url: config?.onboard_url ?? "",
      events_url: config?.events_url ?? "",
    });
  }, [canWrite, config]);

  const { saveMutation, testMutation } = useWebhookMutations({
    appKey,
    canWrite,
    enabled,
    queryKey,
    setOneTimeSecret,
    urls,
  });

  return {
    t,
    configQuery,
    configState,
    config,
    canWrite,
    enabled,
    setEnabled,
    urls,
    setUrls,
    rotateConfirmOpen,
    setRotateConfirmOpen,
    oneTimeSecret,
    setOneTimeSecret,
    saveMutation,
    testMutation,
    submit: (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!canWrite) {
        return;
      }
      saveMutation.mutate(false);
    },
    requestRotate: () => {
      if (!canWrite) {
        return;
      }
      if (config?.secret_configured) {
        setRotateConfirmOpen(true);
        return;
      }
      saveMutation.mutate(true);
    },
    sendTest: (target: WebhookTarget) => {
      testMutation.reset();
      testMutation.mutate(target);
    },
  };
}

function useWebhookMutations({
  appKey,
  canWrite,
  enabled,
  queryKey,
  setOneTimeSecret,
  urls,
}: {
  appKey: string;
  canWrite: boolean;
  enabled: boolean;
  queryKey: readonly unknown[];
  setOneTimeSecret: (secret: string) => void;
  urls: Record<WebhookTarget, string>;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const saveMutation = useMutation({
    mutationFn: async (rotateSecret: boolean) => {
      if (!canWrite) {
        throw new Error(t("webhook.loadFailed"));
      }
      const payload = await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/webhook-config`, {
        method: "PUT",
        body: {
          enabled,
          approval_callback_url: urls.approval_callback_url.trim(),
          handover_url: urls.handover_url.trim(),
          onboard_url: urls.onboard_url.trim(),
          events_url: urls.events_url.trim(),
          rotate_secret: rotateSecret,
        } satisfies JsonObject,
      });
      const parsed = parseWebhookConfigPayload(payload, t("webhook.saveFailed"));
      if (parsed.webhook_config === null) {
        throw new Error(t("webhook.saveFailed"));
      }
      return parsed;
    },
    onSuccess: (payload) => {
      const secret = payload.webhook_config?.secret ?? "";
      // 明文 secret 只在本次响应出现一次: 不进查询缓存, 只放进一次性弹窗状态。
      queryClient.setQueryData(queryKey, {
        webhook_config: payload.webhook_config ? { ...payload.webhook_config, secret: undefined } : null,
      });
      if (secret) {
        setOneTimeSecret(secret);
      }
      toast.success(t("webhook.saveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("webhook.saveFailed"), error.message);
    },
  });
  const testMutation = useMutation({
    mutationFn: (target: WebhookTarget) =>
      apiRequest<WebhookTestResult>(`/console/api/v1/apps/${appKey}/webhook-config/test`, {
        method: "POST",
        body: { target } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      toast.success(t("webhook.testResult", { deliveryId: payload.delivery_id, status: deliveryStateLabel(t, payload.status) }));
    },
    onError: (error: Error) => {
      toast.error(t("webhook.testFailed"), error.message);
    },
  });
  return { saveMutation, testMutation };
}
