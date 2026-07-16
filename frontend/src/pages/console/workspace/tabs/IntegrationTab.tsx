import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Network, PlugZap, RefreshCcw, ShieldCheck } from "lucide-react";

import { Badge } from "../../../../components/Badge";
import { Button } from "../../../../components/Button";
import { Field, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type {
  AppCapabilitiesPayload,
  AppCapabilityItem,
  AppCapabilityKey,
  AppCapabilityPayload,
  AppNotificationChannelPayload,
} from "../../../../lib/domain";

const CAPABILITY_KEYS: AppCapabilityKey[] = ["directory", "notify"];

interface ChannelFormState {
  name: string;
  dingtalkAppKey: string;
  agentId: string;
}

const EMPTY_CHANNEL_FORM: ChannelFormState = {
  name: "",
  dingtalkAppKey: "",
  agentId: "",
};

type ChannelLoadState = "loading" | "error" | "unconfigured" | "configured";

export function IntegrationTab({ appKey, canManage }: { appKey: string; canManage: boolean }) {
  const { t } = useI18n();

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="overflow-hidden">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.55fr)]">
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-ink">
              <ShieldCheck size={18} aria-hidden="true" />
              <h2 className="text-base font-semibold">{t("console.integration.heading")}</h2>
            </div>
            <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("console.integration.description")}</p>
          </div>
          <div className="border-l-2 border-amber/45 bg-amber/8 px-4 py-3">
            <p className="text-label font-semibold uppercase tracking-caps-wide text-amber">
              {t("console.integration.boundaryHeading")}
            </p>
            <p className="mt-1 text-xs leading-5 text-ink-soft">{t("console.integration.boundaryDescription")}</p>
          </div>
        </div>
      </PanelSurface>
      <CapabilityPanel appKey={appKey} />
      <NotificationChannelPanel appKey={appKey} canManage={canManage} />
    </section>
  );
}

function CapabilityPanel({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const queryKey = ["console", "app", appKey, "capabilities"];
  const capabilityQuery = useQuery({
    queryKey,
    queryFn: () => apiRequest<AppCapabilitiesPayload>(`/console/api/v1/apps/${appKey}/capabilities`),
  });
  const canManage = Boolean(capabilityQuery.data?.can_manage);
  const toggleMutation = useMutation({
    mutationFn: ({ item, enabled }: { item: AppCapabilityItem; enabled: boolean }) =>
      apiRequest<AppCapabilityPayload>(`/console/api/v1/apps/${appKey}/capabilities/${item.capability}`, {
        method: "PUT",
        body: { enabled, config: item.config } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData<AppCapabilitiesPayload>(queryKey, (current) => ({
        can_manage: current?.can_manage ?? false,
        capabilities: CAPABILITY_KEYS.map((key) =>
          key === payload.capability.capability
            ? payload.capability
            : capabilityFromPayload(current, key),
        ),
      }));
      toast.success(t("console.integration.capabilitySaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.integration.capabilitySaveFailed"), error.message);
    },
  });

  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Network size={17} aria-hidden="true" />
            <h3 className="text-sm font-semibold text-ink">{t("console.integration.capabilitiesHeading")}</h3>
          </div>
          <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("console.integration.capabilitiesDescription")}</p>
        </div>
        <Badge tone={canManage ? "ink" : "neutral"}>
          {canManage ? t("console.integration.adminMode") : t("console.integration.adminRequiredMode")}
        </Badge>
      </div>
      {capabilityQuery.error ? (
        <StatusBanner
          tone="signal"
          title={t("console.integration.capabilitiesLoadFailed")}
          message={(capabilityQuery.error as Error).message}
        />
      ) : null}
      <div className="grid gap-3 md:grid-cols-2" aria-busy={capabilityQuery.isLoading}>
        {CAPABILITY_KEYS.map((key) => {
          const item = capabilityFromPayload(capabilityQuery.data, key);
          const pending = toggleMutation.isPending && toggleMutation.variables?.item.capability === key;
          return (
            <article key={key} className="border border-ink/12 bg-paper-soft p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    {key === "directory" ? <Network size={15} aria-hidden="true" /> : <BellRing size={15} aria-hidden="true" />}
                    <h4 className="font-mono text-sm font-semibold text-ink">{key}</h4>
                  </div>
                  <p className="text-xs leading-5 text-ink-soft">
                    {t(key === "directory" ? "console.integration.directoryDescription" : "console.integration.notifyDescription")}
                  </p>
                </div>
                {capabilityQuery.isLoading ? (
                  <Badge>{t("common.loading")}</Badge>
                ) : (
                  <Badge tone={item.enabled ? "evergreen" : "faint"}>
                    {item.enabled ? t("common.enabled") : t("common.disabled")}
                  </Badge>
                )}
              </div>
              <label className="mt-4 flex items-center justify-between gap-3 border-t border-ink/10 pt-3 text-body text-ink">
                <span>{t("console.integration.platformGate")}</span>
                <input
                  className="size-4 accent-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent/50"
                  type="checkbox"
                  role="switch"
                  aria-label={t("console.integration.capabilityToggle", { capability: key })}
                  checked={item.enabled}
                  disabled={!canManage || capabilityQuery.isLoading || capabilityQuery.isError || pending}
                  onChange={(event) => toggleMutation.mutate({ item, enabled: event.currentTarget.checked })}
                />
              </label>
            </article>
          );
        })}
      </div>
    </PanelSurface>
  );
}

function NotificationChannelPanel({ appKey, canManage }: { appKey: string; canManage: boolean }) {
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
  const loadState: ChannelLoadState = channelQuery.isLoading
    ? "loading"
    : channelQuery.isError
      ? "error"
      : channel
        ? "configured"
        : "unconfigured";
  const canWriteChannel = canManage && (loadState === "configured" || loadState === "unconfigured");

  useEffect(() => {
    if (!channelQuery.data) {
      return;
    }
    const current = channelQuery.data.notification_channel;
    setForm({
      name: current?.name ?? "",
      dingtalkAppKey: current?.dingtalk_app_key ?? "",
      agentId: current?.agent_id ?? "",
    });
  }, [channelQuery.data]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      const secret = secretInputRef.current?.value ?? "";
      if (secretInputRef.current) {
        secretInputRef.current.value = "";
      }
      setHasSecretInput(false);
      return parseNotificationChannelPayload(
        await apiRequest<unknown>(`/console/api/v1/apps/${appKey}/notification-channel`, {
          method: "PUT",
          body: {
            name: form.name.trim(),
            dingtalk_app_key: form.dingtalkAppKey.trim(),
            dingtalk_app_secret: secret,
            agent_id: form.agentId.trim(),
          } satisfies JsonObject,
        }),
        t("console.integration.channelInvalidResponse"),
      );
    },
    onSuccess: (payload) => {
      queryClient.setQueryData(queryKey, payload);
      toast.success(t("console.integration.channelSaveSuccess"));
    },
    onError: (error: Error) => {
      toast.error(t("console.integration.channelSaveFailed"), error.message);
    },
    onSettled: () => {
      if (secretInputRef.current) {
        secretInputRef.current.value = "";
      }
      setHasSecretInput(false);
    },
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
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (canWriteChannel) {
      saveMutation.mutate();
    }
  };
  const formComplete = Boolean(
    form.name.trim()
    && form.dingtalkAppKey.trim()
    && form.agentId.trim()
    && (channel?.app_secret_configured || hasSecretInput),
  );

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
        <div className="flex items-center gap-2">
          {loadState === "configured" ? <Badge tone="neutral">v{channel?.version}</Badge> : null}
          {loadState === "loading" ? <Badge>{t("common.loading")}</Badge> : null}
          {loadState === "error" ? <Badge tone="signal">{t("console.integration.channelLoadFailed")}</Badge> : null}
          {loadState === "unconfigured" ? <Badge tone="amber">{t("console.integration.channelNotConfigured")}</Badge> : null}
          {loadState === "configured" ? (
            <Badge tone={channel?.app_secret_configured ? "evergreen" : "amber"}>
              {channel?.app_secret_configured ? t("console.integration.secretConfigured") : t("console.integration.secretMissing")}
            </Badge>
          ) : null}
        </div>
      </div>
      {loadState === "loading" ? <StatusBanner title={t("console.integration.channelLoading")} /> : null}
      {loadState === "error" ? (
        <div className="space-y-3">
          <StatusBanner
            tone="signal"
            title={t("console.integration.channelLoadFailed")}
            message={(channelQuery.error as Error).message}
          />
          <Button type="button" icon={<RefreshCcw size={15} />} loading={channelQuery.isFetching} onClick={() => void channelQuery.refetch()}>
            {t("common.retry")}
          </Button>
        </div>
      ) : null}
      {loadState === "unconfigured" ? (
        <StatusBanner tone="amber" title={t("console.integration.channelNotConfigured")} message={t("console.integration.channelEmptyDescription")} />
      ) : null}
      <form className="grid gap-4" onSubmit={submit} aria-busy={channelQuery.isLoading}>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label={t("console.integration.channelName")}>
            <TextInput
              value={form.name}
              disabled={!canWriteChannel || saveMutation.isPending}
              onChange={(event) => {
                const name = event.currentTarget.value;
                setForm((current) => ({ ...current, name }));
              }}
            />
          </Field>
          <Field label={t("console.integration.agentId")} hint={t("console.integration.agentIdHint")}>
            <TextInput
              className="font-mono"
              value={form.agentId}
              disabled={!canWriteChannel || saveMutation.isPending}
              onChange={(event) => {
                const agentId = event.currentTarget.value;
                setForm((current) => ({ ...current, agentId }));
              }}
            />
          </Field>
          <Field label={t("console.integration.dingtalkAppKey")}>
            <TextInput
              className="font-mono"
              autoComplete="off"
              value={form.dingtalkAppKey}
              disabled={!canWriteChannel || saveMutation.isPending}
              onChange={(event) => {
                const dingtalkAppKey = event.currentTarget.value;
                setForm((current) => ({ ...current, dingtalkAppKey }));
              }}
            />
          </Field>
          <Field
            label={t("console.integration.dingtalkAppSecret")}
            hint={channel?.app_secret_configured ? t("console.integration.secretPreserveHint") : t("console.integration.secretRequiredHint")}
          >
            <TextInput
              ref={secretInputRef}
              type="password"
              autoComplete="new-password"
              placeholder={channel?.app_secret_configured ? t("console.integration.secretConfiguredPlaceholder") : ""}
              disabled={!canWriteChannel || saveMutation.isPending}
              onChange={(event) => setHasSecretInput(Boolean(event.currentTarget.value))}
            />
          </Field>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 pt-4">
          <p className="max-w-2xl text-xs leading-5 text-ink-faint">{t("console.integration.queueIdentityHint")}</p>
          <div className="flex gap-2">
            <Button
              type="button"
              loading={testMutation.isPending}
              disabled={!canWriteChannel || !channel || saveMutation.isPending}
              onClick={() => testMutation.mutate()}
            >
              {t("console.integration.testConnectivity")}
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={saveMutation.isPending}
              disabled={!canWriteChannel || !formComplete}
            >
              {t("console.integration.saveNewVersion")}
            </Button>
          </div>
        </div>
      </form>
    </PanelSurface>
  );
}

function capabilityFromPayload(payload: AppCapabilitiesPayload | undefined, key: AppCapabilityKey): AppCapabilityItem {
  return payload?.capabilities.find((item) => item.capability === key) ?? {
    capability: key,
    enabled: false,
    config: {},
  };
}

function parseNotificationChannelPayload(value: unknown, errorMessage: string): AppNotificationChannelPayload {
  if (!isRecord(value) || !("notification_channel" in value)) {
    throw new Error(errorMessage);
  }
  const channel = value.notification_channel;
  if (channel === null) {
    return { notification_channel: null };
  }
  if (
    !isRecord(channel)
    || typeof channel.id !== "number"
    || typeof channel.name !== "string"
    || typeof channel.dingtalk_app_key !== "string"
    || typeof channel.app_secret_configured !== "boolean"
    || typeof channel.agent_id !== "string"
    || typeof channel.version !== "number"
    || typeof channel.is_active !== "boolean"
  ) {
    throw new Error(errorMessage);
  }
  return {
    notification_channel: {
      id: channel.id,
      name: channel.name,
      dingtalk_app_key: channel.dingtalk_app_key,
      app_secret_configured: channel.app_secret_configured,
      agent_id: channel.agent_id,
      version: channel.version,
      is_active: channel.is_active,
      created_by: typeof channel.created_by === "string" ? channel.created_by : undefined,
      created_at: typeof channel.created_at === "string" ? channel.created_at : undefined,
    },
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
