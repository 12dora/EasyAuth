import type { ReactNode } from "react";

import type { AppSummary } from "../../../lib/domain";
import { HandoverCapabilityTab } from "../lifecycle/HandoverCapabilityTab";
import { ManagedScopeTab } from "./managedScope/ManagedScopeTab";
import { CatalogTab } from "./tabs/CatalogTab";
import { ConnectorTab } from "./tabs/ConnectorTab";
import { CredentialsTab } from "./tabs/CredentialsTab";
import { GuideTab } from "./tabs/GuideTab";
import { IntegrationTab } from "./tabs/IntegrationTab";
import { ManifestTab } from "./tabs/ManifestTab";
import { MatrixTab } from "./tabs/MatrixTab";
import { OverviewTab } from "./tabs/OverviewTab";
import { QueryTestTab } from "./tabs/QueryTestTab";
import { RulesTab } from "./tabs/RulesTab";
import { WebhookTab } from "./tabs/WebhookTab";
import type { WorkspaceTab } from "./workspaceTabs";

export interface WorkspaceTabPanelContext {
  appKey: string;
  app?: AppSummary;
  isSuperuser: boolean;
}

const TAB_PANELS: Record<WorkspaceTab, (context: WorkspaceTabPanelContext) => ReactNode> = {
  overview: ({ appKey, app }) => <OverviewTab appKey={appKey} app={app} />,
  catalog: ({ appKey }) => <CatalogTab appKey={appKey} />,
  matrix: ({ appKey, app }) => <MatrixTab appKey={appKey} canManage={app?.capabilities?.can_manage_catalog === true} />,
  "managed-scope": ({ appKey }) => <ManagedScopeTab appKey={appKey} />,
  rules: ({ appKey }) => <RulesTab appKey={appKey} />,
  manifest: ({ appKey }) => <ManifestTab appKey={appKey} />,
  credentials: ({ appKey, app }) => <CredentialsTab appKey={appKey} canManage={app?.capabilities?.can_manage_credentials === true} />,
  integration: ({ appKey, app }) => <IntegrationTab appKey={appKey} canManage={app?.capabilities?.can_edit_basic_info === true} />,
  webhook: ({ appKey }) => <WebhookTab appKey={appKey} />,
  connector: ({ appKey, app }) => <ConnectorTab appKey={appKey} canManage={app?.capabilities?.can_manage_connectors === true} />,
  test: ({ appKey }) => <QueryTestTab appKey={appKey} />,
  guide: ({ appKey }) => <GuideTab appKey={appKey} />,
  handover: ({ appKey, isSuperuser }) => (isSuperuser ? <HandoverCapabilityTab appKey={appKey} /> : null),
};

export function renderWorkspaceTabPanel(activeTab: WorkspaceTab, context: WorkspaceTabPanelContext): ReactNode {
  return TAB_PANELS[activeTab](context);
}
