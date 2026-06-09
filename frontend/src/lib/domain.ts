import type { JsonObject, Pagination } from "./api";

export interface AppSummary {
  id: number;
  app_key: string;
  name: string;
  description?: string;
  is_active?: boolean;
  owners?: string[];
  developers?: string[];
  configuration_status?: string;
  updated_at?: string;
  can_manage?: boolean;
  role_count?: number;
  permission_count?: number;
  active_credential_count?: number;
  configuration_summary?: {
    status?: string;
    issue_count?: number;
    blocking_count?: number;
    warning_count?: number;
  };
}

export interface AppListPayload {
  items?: AppSummary[];
  data?: AppSummary[];
  app?: AppSummary;
  pagination?: Pagination;
}

export interface ConfigurationIssue {
  code?: string;
  severity?: string;
  level?: string;
  message?: string;
  subject?: string;
  target_type?: string;
  target_id?: string;
}

export interface ConfigurationStatus {
  app_key?: string;
  status?: string;
  issues?: ConfigurationIssue[];
  items?: ConfigurationIssue[];
}

export interface RoleItem {
  id: number;
  key: string;
  name: string;
  description?: string;
  requestable?: boolean;
  is_active?: boolean;
}

export interface PermissionItem {
  id: number;
  app_key?: string;
  key: string;
  name: string;
  description?: string;
  group_key?: string;
  is_active?: boolean;
  is_deprecated?: boolean;
}

export interface PermissionGroupItem {
  id: number;
  app_key?: string;
  type: "group";
  key: string;
  name: string;
  description?: string;
  depth?: number;
  children?: Array<PermissionGroupItem | PermissionItem>;
  permissions?: PermissionItem[];
}

export interface PermissionTreePayload {
  app_key?: string;
  groups?: PermissionGroupItem[];
  ungrouped_permissions?: PermissionItem[];
  version?: string;
}

export interface MatrixPayload {
  app_key?: string;
  roles?: RoleItem[];
  permissions?: PermissionItem[];
  assignments?: Array<{ role_key: string; permission_key: string }>;
  cells?: Array<{ role_id: number; permission_id: number; enabled: boolean }>;
  version?: string;
}

export interface ApprovalRuleItem {
  id: number;
  target_type?: string;
  target_key?: string;
  approver_userids?: string[];
  is_active?: boolean;
}

export interface CredentialItem {
  id: number;
  kind: "static_token" | "oauth_client" | string;
  name: string;
  is_active?: boolean;
  client_id?: string;
}

export interface SecretPayload {
  credential?: CredentialItem;
  one_time_secret?: Record<string, string>;
}

export interface IntegrationGuide {
  app_key?: string;
  permission_query_endpoint?: string;
  credential_modes?: Array<{ mode: string; active_count: number }>;
}

export interface QueryTestResult {
  app_key?: string;
  user_id?: string;
  allowed?: boolean;
  roles?: string[];
  permissions?: string[];
  version?: string;
  expires_at?: string | null;
  status_code?: number;
  code?: string;
  explanation?: string;
}

export interface PortalGrant {
  app_key?: string;
  app_name?: string;
  roles?: string[];
  role_names?: string[];
  permissions?: string[];
  version?: number | string;
  grant_type?: string;
  grant_expires_at?: string | null;
}

export interface PortalRequest {
  id?: number;
  app_key?: string;
  app_name?: string;
  roles?: string[];
  role_names?: string[];
  permissions?: string[];
  status?: string;
  status_label?: string;
  request_type?: string;
  grant_type?: string;
  reason?: string;
  submitted_at?: string;
  grant_expires_at?: string | null;
}

export interface PortalCatalogApp {
  id: number;
  app_key: string;
  name: string;
  description?: string;
}

export interface PortalCatalogRole {
  id: number;
  app_key: string;
  key: string;
  name: string;
  description?: string;
  requestable?: boolean;
  requires_approval?: boolean;
}

export interface PortalRequestCatalog {
  apps?: PortalCatalogApp[];
  roles?: PortalCatalogRole[];
  permission_groups?: PermissionGroupItem[];
  ungrouped_permissions?: PermissionItem[];
}

export interface OperationRow {
  id?: number;
  user_id?: string;
  app_key?: string;
  status?: string;
  request_type?: string;
  grant_type?: string;
  reason?: string;
  submitted_at?: string;
  grant_expires_at?: string | null;
  component?: string;
  summary?: string;
  error_summary?: string;
  last_checked_at?: string | null;
}
