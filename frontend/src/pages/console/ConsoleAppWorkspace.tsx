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
  { key: "manifest", label: "Manifest" },
  { key: "credentials", label: "凭据" },
  { key: "test", label: "联调" },
  { key: "guide", label: "接入说明" },
];

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
        eyebrow="Workspace"
        title={app?.name ?? appKey}
        description={app?.description || "应用授权配置、接入凭据和联调入口。"}
        actions={<Link className="button button-secondary" to="/console">返回应用列表</Link>}
      />
      {appQuery.error ? (
        <StatusBanner tone="danger" title="应用加载失败" message={(appQuery.error as Error).message} />
      ) : null}
      <div className="tabbar">
        {TABS.map((item) => (
          <button
            key={item.key}
            className={item.key === activeTab ? "active" : ""}
            onClick={() => setSearchParams({ tab: item.key })}
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
