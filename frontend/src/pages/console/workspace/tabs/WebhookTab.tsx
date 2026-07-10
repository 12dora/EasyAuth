import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, RefreshCcw, Save, Send } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, TextInput } from "../../../../components/Field";
import { SecretDialog } from "../../../../components/SecretDialog";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MessageKey } from "../../../../i18n/messages";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type { WebhookConfigItem, WebhookConfigPayload } from "../../../../lib/domain";
import { deliveryStateLabel, formatDateTime } from "../../../../lib/status";

type WebhookTarget = "approval_callback_url" | "handover_url" | "onboard_url";

const TARGET_FIELDS: Array<{ target: WebhookTarget; labelKey: MessageKey }> = [
  { target: "approval_callback_url", labelKey: "webhook.field.approvalCallbackUrl" },
  { target: "handover_url", labelKey: "webhook.field.handoverUrl" },
  { target: "onboard_url", labelKey: "webhook.field.onboardUrl" },
];

interface WebhookTestResult {
  delivery_id: string;
  status: string;
}

type WebhookConfigState =
  | { status: "loading" }
  | { status: "error"; error: Error }
  | { status: "unconfigured" }
  | { status: "configured"; config: WebhookConfigItem };

export function WebhookTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const queryKey = ["console", "app", appKey, "webhook-config"];
  const [enabled, setEnabled] = useState(true);
  const [urls, setUrls] = useState<Record<WebhookTarget, string>>({
    approval_callback_url: "",
    handover_url: "",
    onboard_url: "",
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
    });
  }, [canWrite, config]);

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

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite) {
      return;
    }
    saveMutation.mutate(false);
  };

  const requestRotate = () => {
    if (!canWrite) {
      return;
    }
    if (config?.secret_configured) {
      setRotateConfirmOpen(true);
      return;
    }
    saveMutation.mutate(true);
  };

  const sendTest = (target: WebhookTarget) => {
    testMutation.reset();
    testMutation.mutate(target);
  };

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="space-y-5">
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
        {configState.status === "error" ? (
          <div className="space-y-3">
            <StatusBanner tone="signal" title={t("webhook.loadFailed")} message={configState.error.message} />
            <Button
              type="button"
              icon={<RefreshCcw size={15} />}
              loading={configQuery.isFetching}
              onClick={() => void configQuery.refetch()}
            >
              {t("common.retry")}
            </Button>
          </div>
        ) : null}
        {configState.status === "unconfigured" ? (
          <StatusBanner tone="amber" title={t("webhook.notConfigured")} />
        ) : null}
        <form className="grid max-w-3xl gap-4" onSubmit={submit}>
          <label className="inline-flex items-center gap-2 text-body text-ink">
            <input
              type="checkbox"
              checked={enabled}
              disabled={!canWrite || saveMutation.isPending}
              onChange={(event) => setEnabled(event.currentTarget.checked)}
            />
            <span>{t("webhook.enabled")}</span>
          </label>
          {TARGET_FIELDS.map(({ target, labelKey }) => (
            <Field key={target} label={t(labelKey)}>
              <div className="flex items-center gap-2">
                <TextInput
                  type="url"
                  autoComplete="off"
                  spellCheck={false}
                  aria-label={t(labelKey)}
                  className="font-mono"
                  value={urls[target]}
                  disabled={!canWrite || saveMutation.isPending}
                  onChange={(event) => {
                    const next = event.currentTarget.value;
                    setUrls((current) => ({ ...current, [target]: next }));
                  }}
                />
                {config?.[target] ? (
                  <Button
                    type="button"
                    size="sm"
                    icon={<Send size={14} />}
                    loading={testMutation.isPending && testMutation.variables === target}
                    disabled={testMutation.isPending}
                    onClick={() => sendTest(target)}
                  >
                    {t("webhook.sendTest")}
                  </Button>
                ) : null}
              </div>
            </Field>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs leading-5 text-ink-faint">
              {config?.updated_at
                ? t("webhook.updatedMeta", { user: config.updated_by || "-", time: formatDateTime(config.updated_at) })
                : null}
            </span>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                icon={<KeyRound size={15} />}
                loading={saveMutation.isPending}
                disabled={saveMutation.isPending || !canWrite}
                onClick={requestRotate}
              >
                {t("webhook.rotate")}
              </Button>
              <Button
                type="submit"
                variant="primary"
                icon={<Save size={15} />}
                loading={saveMutation.isPending}
                disabled={saveMutation.isPending || !canWrite}
              >
                {t("common.save")}
              </Button>
            </div>
          </div>
        </form>
      </PanelSurface>
      {rotateConfirmOpen ? (
        <Dialog
          title={t("webhook.rotateTitle")}
          size="sm"
          onClose={() => setRotateConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setRotateConfirmOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                loading={saveMutation.isPending}
                disabled={saveMutation.isPending || !canWrite}
                onClick={() => {
                  if (!canWrite) {
                    return;
                  }
                  setRotateConfirmOpen(false);
                  saveMutation.mutate(true);
                }}
              >
                {t("webhook.rotateConfirm")}
              </Button>
            </>
          }
        >
          <p className="text-body leading-6 text-ink">{t("webhook.rotateMessage")}</p>
        </Dialog>
      ) : null}
      {oneTimeSecret ? (
        <SecretDialog
          title={t("webhook.secretTitle")}
          primaryLabel="secret"
          primaryValue={oneTimeSecret}
          onClose={() => setOneTimeSecret("")}
        />
      ) : null}
    </section>
  );
}

function parseWebhookConfigPayload(payload: unknown, errorMessage: string): WebhookConfigPayload {
  if (!isRecord(payload) || !("webhook_config" in payload)) {
    throw new Error(errorMessage);
  }
  const config = payload.webhook_config;
  if (config === null) {
    return { webhook_config: null };
  }
  if (
    !isRecord(config) ||
    typeof config.enabled !== "boolean" ||
    typeof config.secret_configured !== "boolean" ||
    typeof config.approval_callback_url !== "string" ||
    typeof config.handover_url !== "string" ||
    typeof config.onboard_url !== "string" ||
    (config.secret !== undefined && typeof config.secret !== "string") ||
    (config.updated_by !== undefined && typeof config.updated_by !== "string") ||
    (config.updated_at !== undefined && config.updated_at !== null && typeof config.updated_at !== "string")
  ) {
    throw new Error(errorMessage);
  }
  return { webhook_config: config as unknown as WebhookConfigPayload["webhook_config"] };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
