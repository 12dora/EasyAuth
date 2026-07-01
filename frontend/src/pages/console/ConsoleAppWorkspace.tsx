import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { apiRequest } from "../../lib/api";
import type { AppListPayload } from "../../lib/domain";
import { CatalogTab } from "./workspace/tabs/CatalogTab";
import { CredentialsTab } from "./workspace/tabs/CredentialsTab";
import { GuideTab } from "./workspace/tabs/GuideTab";
import { ManifestTab } from "./workspace/tabs/ManifestTab";
import { MatrixTab } from "./workspace/tabs/MatrixTab";
import { OverviewTab } from "./workspace/tabs/OverviewTab";
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
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = (searchParams.get("tab") as WorkspaceTab | null) ?? "overview";
  const activeTab = TABS.some((item) => item.key === tab) ? tab : "overview";

  const appQuery = useQuery({
    queryKey: ["console", "app", appKey],
    queryFn: () => apiRequest<AppListPayload>(`/console/api/v1/apps/${appKey}`),
    enabled: Boolean(appKey),
  });
  const app = appQuery.data?.app;

  return (
    <>
      <PageHeader
        eyebrow="控制台工作台"
        title={app?.name ?? appKey}
        description={app?.description || "应用授权配置、接入凭据和联调入口。"}
        actions={
          <Link
            className="inline-flex h-9 items-center justify-center rounded-md border border-[rgb(var(--hairline-strong))] bg-paper-deep px-3.5 text-sm font-medium text-ink transition-colors hover:border-ink-faint hover:bg-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-ink/50"
            to="/console"
          >
            返回应用列表
          </Link>
        }
      />
      {appQuery.error ? (
        <StatusBanner tone="signal" title="应用加载失败" message={(appQuery.error as Error).message} />
      ) : null}
      <div className="mb-6 flex gap-1 overflow-x-auto border-b border-[rgb(var(--hairline))]">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={cn(
              "relative -mb-px h-10 shrink-0 border-b-2 px-3 text-sm font-semibold transition-colors",
              item.key === activeTab
                ? "border-amber-ink text-ink"
                : "border-transparent text-ink-soft hover:border-[rgb(var(--hairline-strong))] hover:text-ink",
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
    </>
  );
}
