import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Button } from "../../components/Button";
import { Field, SelectInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload, AppManagedScopePolicyPayload, EffectiveManagedScopePolicyItem } from "../../lib/domain";
import { CatalogTab } from "./workspace/tabs/CatalogTab";
import { CredentialsTab } from "./workspace/tabs/CredentialsTab";
import { GuideTab } from "./workspace/tabs/GuideTab";
import { ManifestTab } from "./workspace/tabs/ManifestTab";
import { MatrixTab } from "./workspace/tabs/MatrixTab";
import { AppBasicInfoDialog, type AppPatchPayload, OverviewTab } from "./workspace/tabs/OverviewTab";
import { QueryTestTab } from "./workspace/tabs/QueryTestTab";
import { RulesTab } from "./workspace/tabs/RulesTab";

type WorkspaceTab = "overview" | "catalog" | "matrix" | "managed-scope" | "rules" | "manifest" | "credentials" | "test" | "guide";

const TABS: Array<{ key: WorkspaceTab; label: string }> = [
  { key: "overview", label: "总览" },
  { key: "catalog", label: "权限目录" },
  { key: "matrix", label: "授权组" },
  { key: "managed-scope", label: "管理范围" },
  { key: "rules", label: "审批规则" },
  { key: "manifest", label: "清单" },
  { key: "credentials", label: "凭据" },
  { key: "test", label: "联调" },
  { key: "guide", label: "接入说明" },
];

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function ConsoleAppWorkspace() {
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
        eyebrow="控制台工作台"
        title={app?.name ?? appKey}
        description={app?.description || "应用授权配置、接入凭据和联调入口。"}
        actions={
          <div className="flex flex-col items-stretch gap-2 sm:items-end">
            <Link
              className="inline-flex h-9 shrink-0 items-center justify-center gap-2 rounded-[2px] border border-ink/30 bg-transparent px-3.5 text-[13px] font-medium tracking-wide text-ink transition-all duration-150 hover:border-ink/60 hover:bg-ink/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--amber)_/_0.5)] active:[transform:translateY(1px)]"
              to="/console"
            >
              返回应用列表
            </Link>
            {app?.can_manage ? (
              <Button
                type="button"
                onClick={() => {
                  patchAppMutation.reset();
                  setBasicInfoEditing(true);
                }}
              >
                编辑
              </Button>
            ) : null}
          </div>
        }
      />
      {appQuery.error ? (
        <StatusBanner tone="signal" title="应用加载失败" message={(appQuery.error as Error).message} />
      ) : null}
      <div className="relative mb-6 flex gap-1 overflow-x-auto border-b border-[rgb(var(--hairline))]">
        <span
          aria-hidden="true"
          className="pointer-events-none absolute bottom-0 h-0.5 bg-amber-ink transition-[left,width] duration-200 ease-out"
          style={{ left: indicatorStyle.left, width: indicatorStyle.width }}
        />
        {TABS.map((item, index) => (
          <button
            key={item.key}
            ref={(node) => {
              tabButtonRefs.current[index] = node;
            }}
            className={cn(
              "relative z-10 h-10 shrink-0 px-3 text-sm font-semibold transition-colors",
              item.key === activeTab
                ? "text-ink"
                : "text-ink-soft hover:text-ink",
            )}
            onClick={() => setSearchParams({ tab: item.key })}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </div>
      {activeTab === "overview" ? <OverviewTab appKey={appKey} app={app} /> : null}
      {activeTab === "catalog" ? <CatalogTab appKey={appKey} /> : null}
      {activeTab === "matrix" ? <MatrixTab appKey={appKey} /> : null}
      {activeTab === "managed-scope" ? <ManagedScopeTab appKey={appKey} /> : null}
      {activeTab === "rules" ? <RulesTab appKey={appKey} /> : null}
      {activeTab === "manifest" ? <ManifestTab appKey={appKey} /> : null}
      {activeTab === "credentials" ? <CredentialsTab appKey={appKey} /> : null}
      {activeTab === "test" ? <QueryTestTab appKey={appKey} /> : null}
      {activeTab === "guide" ? <GuideTab appKey={appKey} /> : null}
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

type ManagedScopeSelection = "unconfigured" | "dingtalk_manager_chain" | "disabled";

function ManagedScopeTab({ appKey }: { appKey: string }) {
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
            <h2 className="text-base font-semibold text-ink">管理范围</h2>
            <p className="max-w-3xl text-[13px] leading-5 text-ink-soft">
              配置应用默认的 MANAGED_USERS 解析策略。授权组 grant 可以继承这里的默认策略，也可以单独覆盖。
            </p>
          </div>
          <Button
            type="button"
            variant="primary"
            loading={saveMutation.isPending}
            disabled={saveMutation.isPending || policyQuery.isLoading}
            onClick={() => saveMutation.mutate()}
          >
            保存策略
          </Button>
        </div>
        {policyQuery.error ? (
          <StatusBanner tone="signal" title="管理范围加载失败" message={(policyQuery.error as Error).message} />
        ) : null}
        {saveMutation.error ? (
          <StatusBanner tone="signal" title="管理范围保存失败" message={(saveMutation.error as Error).message} />
        ) : null}
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
          <Field
            label="应用默认 MANAGED_USERS 策略"
            hint="按钉钉主管关系会从上游目录解析当前用户的下属；不启用会阻断继承该默认策略的 MANAGED_USERS grant。"
          >
            <SelectInput
              value={selection}
              onChange={(event) => setSelection(event.currentTarget.value as ManagedScopeSelection)}
              disabled={policyQuery.isLoading || saveMutation.isPending}
            >
              <option value="unconfigured">未配置</option>
              <option value="dingtalk_manager_chain">按钉钉主管关系</option>
              <option value="disabled">不启用</option>
            </SelectInput>
          </Field>
          <div className="rounded-[3px] border border-ink/10 bg-paper-soft p-4">
            <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-ink-soft">当前有效策略</p>
            <p className="mt-2 text-sm font-semibold text-ink">{effectiveManagedScopeLabel(effectivePolicy)}</p>
            <dl className="mt-3 grid gap-2 text-[13px] text-ink-soft">
              <div className="flex items-center justify-between gap-4">
                <dt>来源</dt>
                <dd className="font-mono text-ink">{managedScopeSourceLabel(effectivePolicy?.source)}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt>健康状态</dt>
                <dd className="font-mono text-ink">{managedScopeHealthLabel(effectivePolicy)}</dd>
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
  return { mode: "override", resolver: "dingtalk_manager_chain", enabled: true };
}

function selectionFromManagedScopePayload(payload: AppManagedScopePolicyPayload): ManagedScopeSelection {
  const policy = payload.managed_scope_policy;
  if (!policy) {
    return "unconfigured";
  }
  if (policy.mode === "disabled" || policy.resolver === "disabled" || policy.enabled === false) {
    return "disabled";
  }
  if (policy.resolver === "dingtalk_manager_chain") {
    return "dingtalk_manager_chain";
  }
  return "unconfigured";
}

function effectiveManagedScopeLabel(policy: EffectiveManagedScopePolicyItem | null): string {
  if (!policy?.resolver) {
    return "未配置";
  }
  if (policy.resolver === "disabled") {
    return "不启用";
  }
  if (policy.resolver === "dingtalk_manager_chain") {
    return "按钉钉主管关系";
  }
  return policy.resolver;
}

function managedScopeSourceLabel(source: EffectiveManagedScopePolicyItem["source"] | undefined): string {
  if (source === "app_default") {
    return "应用默认";
  }
  if (source === "authorization_group_grant") {
    return "授权组覆盖";
  }
  return "未配置";
}

function managedScopeHealthLabel(policy: EffectiveManagedScopePolicyItem | null): string {
  const health = policy?.health_status;
  if (health === "healthy") {
    return "正常";
  }
  if (health === "disabled") {
    return "不启用";
  }
  if (health === "blocked") {
    return "阻塞";
  }
  if (health === "warning") {
    return "警告";
  }
  return "未配置";
}
