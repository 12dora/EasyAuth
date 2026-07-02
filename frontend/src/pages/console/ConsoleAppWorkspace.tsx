import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { AppListPayload } from "../../lib/domain";
import { CatalogTab } from "./workspace/tabs/CatalogTab";
import { CredentialsTab } from "./workspace/tabs/CredentialsTab";
import { GuideTab } from "./workspace/tabs/GuideTab";
import { ManifestTab } from "./workspace/tabs/ManifestTab";
import { MatrixTab } from "./workspace/tabs/MatrixTab";
import { AppBasicInfoDialog, type AppPatchPayload, OverviewTab } from "./workspace/tabs/OverviewTab";
import { QueryTestTab } from "./workspace/tabs/QueryTestTab";
import { RulesTab } from "./workspace/tabs/RulesTab";

type WorkspaceTab = "overview" | "catalog" | "matrix" | "rules" | "manifest" | "credentials" | "test" | "guide";

const TABS: Array<{ key: WorkspaceTab; label: string }> = [
  { key: "overview", label: "总览" },
  { key: "catalog", label: "权限目录" },
  { key: "matrix", label: "授权组" },
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
