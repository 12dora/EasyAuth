import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Network } from "lucide-react";

import { Badge } from "../../../../components/Badge";
import { StatusBanner } from "../../../../components/StatusBanner";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { JsonObject } from "../../../../lib/api";
import type { AppCapabilitiesPayload, AppCapabilityItem, AppCapabilityKey, AppCapabilityPayload } from "../../../../lib/domain";
import { invalidateAppDerivedQueries } from "../invalidateAppQueries";

const CAPABILITY_KEYS: AppCapabilityKey[] = ["directory", "notify"];

export function CapabilityPanel({ appKey }: { appKey: string }) {
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
      invalidateAppDerivedQueries(queryClient, appKey);
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
        <StatusBanner live="alert"
          tone="signal"
          title={t("console.integration.capabilitiesLoadFailed")}
          message={capabilityQuery.error.message}
        />
      ) : null}
      <div className="grid gap-3 md:grid-cols-2" aria-busy={capabilityQuery.isLoading}>
        {CAPABILITY_KEYS.map((key) => (
          <CapabilityCard
            key={key}
            capabilityKey={key}
            item={capabilityFromPayload(capabilityQuery.data, key)}
            isLoading={capabilityQuery.isLoading}
            disabled={!canManage || capabilityQuery.isLoading || capabilityQuery.isError
              || (toggleMutation.isPending && toggleMutation.variables?.item.capability === key)}
            onToggle={(item, enabled) => toggleMutation.mutate({ item, enabled })}
          />
        ))}
      </div>
    </PanelSurface>
  );
}

function CapabilityCard({
  capabilityKey,
  item,
  isLoading,
  disabled,
  onToggle,
}: {
  capabilityKey: AppCapabilityKey;
  item: AppCapabilityItem;
  isLoading: boolean;
  disabled: boolean;
  onToggle: (item: AppCapabilityItem, enabled: boolean) => void;
}) {
  const { t } = useI18n();

  return (
    <article className="border border-ink/12 bg-paper-soft p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            {capabilityKey === "directory" ? <Network size={15} aria-hidden="true" /> : <BellRing size={15} aria-hidden="true" />}
            <h4 className="font-mono text-sm font-semibold text-ink">{capabilityKey}</h4>
          </div>
          <p className="text-xs leading-5 text-ink-soft">
            {t(capabilityKey === "directory" ? "console.integration.directoryDescription" : "console.integration.notifyDescription")}
          </p>
        </div>
        {isLoading ? (
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
          aria-label={t("console.integration.capabilityToggle", { capability: capabilityKey })}
          checked={item.enabled}
          disabled={disabled}
          onChange={(event) => onToggle(item, event.currentTarget.checked)}
        />
      </label>
    </article>
  );
}

function capabilityFromPayload(payload: AppCapabilitiesPayload | undefined, key: AppCapabilityKey): AppCapabilityItem {
  return payload?.capabilities.find((item) => item.capability === key) ?? {
    capability: key,
    enabled: false,
    config: {},
  };
}
