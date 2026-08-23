/** 本模块定义应用工作区与权限目录领域契约。 */

import type { JsonObject, Pagination } from "./common";

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
  capabilities?: AppActionCapabilities;
  authorization_group_count?: number;
  permission_count?: number;
  active_credential_count?: number;
  configuration_summary?: {
    status?: string;
    issue_count?: number;
    blocking_count?: number;
    warning_count?: number;
  };
}

export interface AppActionCapabilities {
  can_view?: boolean;
  can_edit_basic_info?: boolean;
  can_toggle_active?: boolean;
  can_delete?: boolean;
  can_manage_memberships?: boolean;
  can_manage_catalog?: boolean;
  can_manage_credentials?: boolean;
  can_manage_connectors?: boolean;
  can_manage_platform_capabilities?: boolean;
}

export interface AppListPayload {
  data?: AppSummary[];
  app?: AppSummary;
  pagination?: Pagination;
}

export interface AppCreatePayload {
  app_key: string;
  name: string;
  description?: string;
  owner_user_ids?: string[];
  developer_user_ids?: string[];
  is_active?: boolean;
}

export interface AppUpdatePayload {
  name?: string;
  description?: string;
  owner_user_ids?: string[];
  developer_user_ids?: string[];
  is_active?: boolean;
}

export interface AppMembershipItem {
  id: number;
  user_id: string;
  role: "owner" | "developer" | string;
  is_active: boolean;
}

export interface AppScopeItem {
  key: string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  is_active: boolean;
  display_order: number;
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
  data?: ConfigurationIssue[];
}

export interface PermissionItem {
  id: number;
  app_key?: string;
  key: string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  group_key?: string;
  is_active?: boolean;
  is_deprecated?: boolean;
  supported_scopes?: string[];
  risk_level?: "low" | "medium" | "high" | string;
  deprecated_at?: string | null;
}

export interface ManagedScopePolicyItem {
  mode: "inherit" | "override" | "disabled" | string;
  resolver?: "dingtalk_manager_chain" | "easyauth_team" | "union" | "disabled" | string | null;
  enabled?: boolean;
}

export interface EffectiveManagedScopePolicyItem {
  resolver?: "dingtalk_manager_chain" | "easyauth_team" | "union" | "disabled" | string | null;
  source?: "app_default" | "authorization_group_grant" | string | null;
  inherited_from?: "app_default" | "authorization_group_grant" | string | null;
  health_status?: "healthy" | "warning" | "blocked" | "disabled" | string | null;
  health_message?: string | null;
}

export interface AppManagedScopePolicyPayload {
  managed_scope_policy?: ManagedScopePolicyItem | null;
  effective_managed_scope_policy?: EffectiveManagedScopePolicyItem | null;
}

export interface TeamLeaderRef {
  user_id: string;
  name: string;
}

export interface TeamSummary {
  id: number;
  name: string;
  description?: string;
  is_active: boolean;
  leaders: TeamLeaderRef[];
  member_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface TeamMemberItem {
  id: number;
  user_id: string;
  name?: string;
  email?: string;
  department?: string;
  status?: string;
  role: "leader" | "member" | string;
  added_at?: string;
}

export interface TeamDetail extends TeamSummary {
  members?: TeamMemberItem[];
}

export interface TeamPayload {
  team?: TeamDetail;
}

export interface AuthorizationGroupGrantItem {
  permission: string;
  scope: string;
  is_active: boolean;
  managed_scope_policy?: ManagedScopePolicyItem;
  effective_managed_scope_policy?: EffectiveManagedScopePolicyItem | null;
}

export interface AuthorizationGroupItem {
  id?: number;
  app_key?: string;
  key: string;
  kind: "role" | "bundle" | string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  requestable: boolean;
  is_active: boolean;
  grants: AuthorizationGroupGrantItem[];
}

export interface PermissionGroupItem {
  id: number;
  app_key?: string;
  type: "group";
  key: string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  depth?: number;
  children?: Array<PermissionGroupItem | PermissionItem>;
  permissions?: PermissionItem[];
}

export interface PermissionTreePayload {
  app_key?: string;
  groups?: PermissionGroupItem[];
  ungrouped_permissions?: PermissionItem[];
  catalog_version?: number;
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
  capabilities?: AppCapabilityKey[];
}

export type AppCapabilityKey = "directory" | "notify";

export interface AppCapabilityItem {
  capability: AppCapabilityKey;
  enabled: boolean;
  config: JsonObject;
  updated_by?: string;
  updated_at?: string | null;
  created_at?: string | null;
}

export interface AppCapabilitiesPayload {
  capabilities: AppCapabilityItem[];
  can_manage: boolean;
}

export interface AppCapabilityPayload {
  capability: AppCapabilityItem;
}

export interface AppNotificationChannel {
  id: number;
  name: string;
  dingtalk_app_key: string;
  app_secret_configured: boolean;
  agent_id: string;
  directory_source_slug: string;
  corp_id: string;
  version: number;
  is_active: boolean;
  created_by?: string;
  created_at?: string;
}

export interface DirectoryScopeItem {
  directory_source_slug: string;
  corp_id: string;
}

export interface AppNotificationChannelPayload {
  notification_channel: AppNotificationChannel | null;
  available_directory_scopes: DirectoryScopeItem[];
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

export interface ResolvedManagedUsers {
  user_ids: string[];
  resolver: string;
  resolved_at: string;
}

export interface ExpandedGrantItem {
  permission: string;
  scope: string;
  source_type: "group" | "direct" | string;
  source_key: string;
  resolved?: ResolvedManagedUsers;
}

export interface PermissionQueryGroupItem {
  key: string;
  kind: "role" | "bundle" | string;
  name: string;
}

export interface PermissionQueryResult {
  app_key?: string;
  user_id?: string;
  groups?: PermissionQueryGroupItem[];
  grants?: ExpandedGrantItem[];
  grant_version?: number;
  catalog_version?: number;
  snapshot_version?: string;
  expires_at?: string | null;
}

export interface QueryTestResult extends PermissionQueryResult {
  allowed?: boolean;
  status_code?: number;
  code?: string;
  explanation?: string;
}

