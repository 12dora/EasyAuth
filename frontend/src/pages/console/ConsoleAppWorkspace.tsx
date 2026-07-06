import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { Field, SelectInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/messages";
import { apiRequest } from "../../lib/api";
import { cn } from "../../lib/cn";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload, AppManagedScopePolicyPayload, EffectiveManagedScopePolicyItem } from "../../lib/domain";
import type { Translator } from "../../lib/status";
import { CatalogTab } from "./workspace/tabs/CatalogTab";
import { CredentialsTab } from "./workspace/tabs/CredentialsTab";
import { GuideTab } from "./workspace/tabs/GuideTab";
import { ManifestTab } from "./workspace/tabs/ManifestTab";
import { MatrixTab } from "./workspace/tabs/MatrixTab";
import { AppBasicInfoDialog, type AppPatchPayload, OverviewTab } from "./workspace/tabs/OverviewTab";
import { QueryTestTab } from "./workspace/tabs/QueryTestTab";
import { RulesTab } from "./workspace/tabs/RulesTab";

type WorkspaceTab = "overview" | "catalog" | "matrix" | "managed-scope" | "rules" | "manifest" | "credentials" | "test" | "guide";

const TABS: Array<{ key: WorkspaceTab; labelKey: MessageKey }> = [
  { key: "overview", labelKey: "workspace.tab.overview" },
  { key: "catalog", labelKey: "workspace.tab.catalog" },
  { key: "matrix", labelKey: "workspace.tab.matrix" },
  { key: "managed-scope", labelKey: "workspace.tab.managedScope" },
  { key: "rules", labelKey: "workspace.tab.rules" },
  { key: "manifest", labelKey: "workspace.tab.manifest" },
  { key: "credentials", labelKey: "workspace.tab.credentials" },
  { key: "test", labelKey: "workspace.tab.test" },
  { key: "guide", labelKey: "workspace.tab.guide" },
];

export function ConsoleAppWorkspace() {
  const { t } = useI18n();
  const { appKey = "" } = useParams();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = (searchParams.get("tab") as WorkspaceTab | null) ?? "overview";
  const activeTab = TABS.some((item) => item.key === tab) ? tab : "overview";
  const activeTabIndex = TABS.findIndex((item) => item.key === activeTab);
  const tabButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [indicatorStyle, setIndicatorStyle] = useState({ left: 0, width: 0 });
  const [basicInfoEditing, setBasicInfoEditing] = useState(false);

  const appQuery = useQuery({
    queryKey: ["console", "app", appKey],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps/${appKey}`),
    enabled: Boolean(appKey),
  });
  const app = appQuery.data?.app;
  const patchAppMutation = useMutation({
    mutationFn: (payload: AppPatchPayload) =>
      apiRequest(`/console/api/v1/apps/${appKey}`, {
        method: "PATCH",
        body: { ...payload } satisfies JsonObject,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "app", appKey] });
      setBasicInfoEditing(false);
    },
  });

  useEffect(() => {
    patchAppMutation.reset();
    setBasicInfoEditing(false);
  }, [appKey]);

  useLayoutEffect(() => {
    const activeButton = tabButtonRefs.current[activeTabIndex];
    if (!activeButton) {
      return;
    }
    const updateIndicator = () => {
      setIndicatorStyle({
        left: activeButton.offsetLeft,
        width: activeButton.offsetWidth,
      });
    };

    updateIndicator();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateIndicator);
    observer?.observe(activeButton);
    if (activeButton.parentElement) {
      observer?.observe(activeButton.parentElement);
    }
    window.addEventListener("resize", updateIndicator);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateIndicator);
    };
  }, [activeTabIndex]);

  return (
    <>
      <PageHeader
        eyebrow={t("workspace.eyebrow")}
        title={app?.name ?? appKey}
        description={app?.description || t("workspace.defaultDescription")}
        actions={
          <div className="flex flex-col items-stretch gap-2 sm:items-end">
            <ButtonLink to="/console">{t("workspace.backToList")}</ButtonLink>
            {app?.can_manage ? (
              <Button
                type="button"
                onClick={() => {
                  patchAppMutation.reset();
                  setBasicInfoEditing(true);
                }}
              >
                {t("workspace.edit")}
              </Button>
            ) : null}
          </div>
        }
      />
      {appQuery.error ? (
        <StatusBanner tone="signal" title={t("workspace.loadFailed")} message={(appQuery.error as Error).message} />
      ) : null}
      <div className="relative mb-6 flex gap-1 overflow-x-auto border-b border-ink/12" role="tablist" aria-label={t("workspace.tablist")}>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0 h-0.5 bg-accent transition-[left,width] duration-200 ease-out"
          style={{ left: indicatorStyle.left, width: indicatorStyle.width }}
        />
        {TABS.map((item, index) => (
          <button
            key={item.key}
            ref={(node) => {
              tabButtonRefs.current[index] = node;
            }}
            role="tab"
            id={`workspace-tab-${item.key}`}
            aria-selected={item.key === activeTab}
            aria-controls="workspace-tabpanel"
            className={cn(
              "relative z-10 h-10 shrink-0 px-3 text-sm font-semibold transition-colors",
              item.key === activeTab
                ? "text-ink"
                : "text-ink-soft hover:text-ink",
            )}
            onClick={() => setSearchParams({ tab: item.key })}
            type="button"
          >
            {t(item.labelKey)}
          </button>
        ))}
      </div>
      <div id="workspace-tabpanel" role="tabpanel" aria-labelledby={`workspace-tab-${activeTab}`}>
      {activeTab === "overview" ? <OverviewTab appKey={appKey} app={app} /> : null}
      {activeTab === "catalog" ? <CatalogTab appKey={appKey} /> : null}
      {activeTab === "matrix" ? <MatrixTab appKey={appKey} /> : null}
      {activeTab === "managed-scope" ? <ManagedScopeTab appKey={appKey} /> : null}
      {activeTab === "rules" ? <RulesTab appKey={appKey} /> : null}
      {activeTab === "manifest" ? <ManifestTab appKey={appKey} /> : null}
      {activeTab === "credentials" ? <CredentialsTab appKey={appKey} /> : null}
      {activeTab === "test" ? <QueryTestTab appKey={appKey} /> : null}
      {activeTab === "guide" ? <GuideTab appKey={appKey} /> : null}
      </div>
      {app?.can_manage && basicInfoEditing ? (
        <AppBasicInfoDialog
          app={app}
          errorMessage={patchAppMutation.error ? (patchAppMutation.error as Error).message : ""}
          isSubmitting={patchAppMutation.isPending}
          onClose={() => setBasicInfoEditing(false)}
          onSubmit={(payload) => patchAppMutation.mutate(payload)}
        />
      ) : null}
    </>
  );
}

type ManagedScopeSelection = "unconfigured" | "dingtalk_manager_chain" | "easyauth_team" | "union" | "disabled";

const MANAGED_SCOPE_RESOLVERS = ["dingtalk_manager_chain", "easyauth_team", "union"] as const;

const MANAGED_SCOPE_OPTIONS: Array<{ value: ManagedScopeSelection; labelKey: MessageKey }> = [
  { value: "unconfigured", labelKey: "console.managedScope.option.unconfigured" },
  { value: "dingtalk_manager_chain", labelKey: "console.managedScope.option.dingtalk" },
  { value: "easyauth_team", labelKey: "console.managedScope.option.team" },
  { value: "union", labelKey: "console.managedScope.option.union" },
  { value: "disabled", labelKey: "console.managedScope.option.disabled" },
];

function ManagedScopeTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [selection, setSelection] = useState<ManagedScopeSelection>("unconfigured");
  const queryKey = ["console", "app", appKey, "managed-scope-policy"];
  const policyQuery = useQuery({
    queryKey,
    queryFn: () => apiRequest<AppManagedScopePolicyPayload>(`/console/api/v1/apps/${appKey}/managed-scope-policy`),
    enabled: Boolean(appKey),
  });
  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest<AppManagedScopePolicyPayload>(`/console/api/v1/apps/${appKey}/managed-scope-policy`, {
        method: "PATCH",
        body: { managed_scope_policy: payloadForManagedScopeSelection(selection) } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(queryKey, payload);
    },
  });
  const effectivePolicy = policyQuery.data?.effective_managed_scope_policy ?? null;
  const teamBasedSelection = selection === "easyauth_team" || selection === "union";

  useEffect(() => {
    if (!policyQuery.data) {
      return;
    }
    setSelection(selectionFromManagedScopePayload(policyQuery.data));
  }, [policyQuery.data]);

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <h2 className="text-base font-semibold text-ink">{t("console.managedScope.heading")}</h2>
            <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("console.managedScope.description")}</p>
          </div>
          <Button
            type="button"
            variant="primary"
            loading={saveMutation.isPending}
            disabled={saveMutation.isPending || policyQuery.isLoading}
            onClick={() => saveMutation.mutate()}
          >
            {t("console.managedScope.save")}
          </Button>
        </div>
        {policyQuery.error ? (
          <StatusBanner tone="signal" title={t("console.managedScope.loadFailed")} message={(policyQuery.error as Error).message} />
        ) : null}
        {saveMutation.error ? (
          <StatusBanner tone="signal" title={t("console.managedScope.saveFailed")} message={(saveMutation.error as Error).message} />
        ) : null}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <div className="space-y-2">
            <Field label={t("console.managedScope.policyLabel")} hint={t("console.managedScope.policyHint")}>
              <SelectInput
                value={selection}
                onChange={(event) => setSelection(event.currentTarget.value as ManagedScopeSelection)}
                disabled={policyQuery.isLoading || saveMutation.isPending}
              >
                {MANAGED_SCOPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {t(option.labelKey)}
                  </option>
                ))}
              </SelectInput>
            </Field>
            {teamBasedSelection ? (
              <p className="text-xs leading-5 text-ink-soft">
                {t("console.managedScope.teamHint")}{" "}
                <Link className="font-medium text-accent hover:underline" to="/console/teams">
                  {t("console.managedScope.teamHintLink")}
                </Link>
              </p>
            ) : null}
          </div>
          <div className="rounded-[3px] border border-ink/10 bg-paper-soft p-4">
            <p className="text-label font-medium uppercase tracking-caps-wide text-ink-soft">{t("console.managedScope.effectiveTitle")}</p>
            <p className="mt-2 text-sm font-semibold text-ink">{effectiveManagedScopeLabel(t, effectivePolicy)}</p>
            <dl className="mt-3 grid gap-2 text-body text-ink-soft">
              <div className="flex items-center justify-between gap-4">
                <dt>{t("console.managedScope.effective.source")}</dt>
                <dd className="font-mono text-ink">{managedScopeSourceLabel(t, effectivePolicy?.source)}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt>{t("console.managedScope.effective.health")}</dt>
                <dd className="font-mono text-ink">{managedScopeHealthLabel(t, effectivePolicy)}</dd>
              </div>
            </dl>
            {effectivePolicy?.health_message ? (
              <p className="mt-3 text-xs leading-5 text-ink-soft">{effectivePolicy.health_message}</p>
            ) : null}
          </div>
        </div>
      </PanelSurface>
    </section>
  );
}

function payloadForManagedScopeSelection(selection: ManagedScopeSelection): JsonObject | null {
  if (selection === "unconfigured") {
    return null;
  }
  if (selection === "disabled") {
    return { mode: "disabled", resolver: "disabled", enabled: false };
  }
  return { mode: "override", resolver: selection, enabled: true };
}

function isManagedScopeResolver(value: unknown): value is (typeof MANAGED_SCOPE_RESOLVERS)[number] {
  return MANAGED_SCOPE_RESOLVERS.includes(value as (typeof MANAGED_SCOPE_RESOLVERS)[number]);
}

function selectionFromManagedScopePayload(payload: AppManagedScopePolicyPayload): ManagedScopeSelection {
  const policy = payload.managed_scope_policy;
  if (!policy) {
    return "unconfigured";
  }
  if (policy.mode === "disabled" || policy.resolver === "disabled" || policy.enabled === false) {
    return "disabled";
  }
  if (isManagedScopeResolver(policy.resolver)) {
    return policy.resolver;
  }
  return "unconfigured";
}

const MANAGED_SCOPE_RESOLVER_LABEL_KEYS: Record<string, MessageKey> = {
  dingtalk_manager_chain: "console.managedScope.option.dingtalk",
  easyauth_team: "console.managedScope.option.team",
  union: "console.managedScope.option.union",
  disabled: "console.managedScope.option.disabled",
};

function effectiveManagedScopeLabel(t: Translator, policy: EffectiveManagedScopePolicyItem | null): string {
  if (!policy?.resolver) {
    return t("console.managedScope.option.unconfigured");
  }
  const labelKey = MANAGED_SCOPE_RESOLVER_LABEL_KEYS[policy.resolver];
  return labelKey ? t(labelKey) : policy.resolver;
}

function managedScopeSourceLabel(t: Translator, source: EffectiveManagedScopePolicyItem["source"] | undefined): string {
  if (source === "app_default") {
    return t("console.managedScope.source.appDefault");
  }
  if (source === "authorization_group_grant") {
    return t("console.managedScope.source.grantOverride");
  }
  return t("console.managedScope.source.unconfigured");
}

const MANAGED_SCOPE_HEALTH_LABEL_KEYS: Record<string, MessageKey> = {
  healthy: "console.managedScope.health.healthy",
  warning: "console.managedScope.health.warning",
  blocked: "console.managedScope.health.blocked",
  disabled: "console.managedScope.health.disabled",
};

function managedScopeHealthLabel(t: Translator, policy: EffectiveManagedScopePolicyItem | null): string {
  const health = policy?.health_status;
  const labelKey = health ? MANAGED_SCOPE_HEALTH_LABEL_KEYS[health] : undefined;
  return labelKey ? t(labelKey) : t("console.managedScope.health.unconfigured");
}
