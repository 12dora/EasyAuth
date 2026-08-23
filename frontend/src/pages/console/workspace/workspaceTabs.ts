import type { MessageKey } from "../../../i18n/messages";

export type WorkspaceTab =
  | "overview"
  | "catalog"
  | "matrix"
  | "managed-scope"
  | "rules"
  | "manifest"
  | "credentials"
  | "integration"
  | "webhook"
  | "connector"
  | "test"
  | "guide"
  | "handover";

export interface WorkspaceTabDescriptor {
  key: WorkspaceTab;
  labelKey: MessageKey;
}

export const BASE_TABS: WorkspaceTabDescriptor[] = [
  { key: "overview", labelKey: "workspace.tab.overview" },
  { key: "catalog", labelKey: "workspace.tab.catalog" },
  { key: "matrix", labelKey: "workspace.tab.matrix" },
  { key: "managed-scope", labelKey: "workspace.tab.managedScope" },
  { key: "rules", labelKey: "workspace.tab.rules" },
  { key: "manifest", labelKey: "workspace.tab.manifest" },
  { key: "credentials", labelKey: "workspace.tab.credentials" },
  { key: "integration", labelKey: "workspace.tab.integration" },
  { key: "webhook", labelKey: "workspace.tab.webhook" },
  { key: "connector", labelKey: "workspace.tab.connector" },
  { key: "test", labelKey: "workspace.tab.test" },
  { key: "guide", labelKey: "workspace.tab.guide" },
];
