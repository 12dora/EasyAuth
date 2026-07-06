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

/** 历史兼容类型：新授权模型应优先使用 AuthorizationGroupItem。 */
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
  /** 历史兼容字段：公共查询主契约已切到 groups。 */
  roles?: string[];
  /** 历史兼容字段：公共查询主契约已切到 grants。 */
  permissions?: string[];
  /** 历史兼容字段：公共查询主契约已切到 grant_version/catalog_version/snapshot_version。 */
  version?: string;
  status_code?: number;
  code?: string;
  explanation?: string;
}

export interface PortalGrant {
  app_key?: string;
  app_name?: string;
  groups?: PermissionQueryGroupItem[];
  grants?: ExpandedGrantItem[];
  grant_version?: number;
  catalog_version?: number;
  snapshot_version?: string;
  /** 历史兼容字段：门户展示应迁移到 groups。 */
  roles?: string[];
  /** 历史兼容字段：门户展示应迁移到 groups。 */
  role_names?: string[];
  /** 历史兼容字段：门户展示应迁移到 grants。 */
  permissions?: string[];
  /** 历史兼容字段：门户展示应迁移到 grant_version/catalog_version/snapshot_version。 */
  version?: number | string;
  grant_type?: string;
  grant_expires_at?: string | null;
}

export interface PortalDirectGrantItem {
  permission: string;
  permission_name?: string;
  scope: string;
}

export interface PortalRequest {
  id?: number;
  app_key?: string;
  app_name?: string;
  authorization_groups?: PermissionQueryGroupItem[];
  direct_grants?: PortalDirectGrantItem[];
  /** 历史兼容字段：申请目标应迁移到 authorization_groups。 */
  roles?: string[];
  /** 历史兼容字段：申请目标应迁移到 authorization_groups。 */
  role_names?: string[];
  /** 历史兼容字段：申请目标应迁移到 direct_grants。 */
  permissions?: string[];
  status?: string;
  status_label?: string;
  request_type?: string;
  grant_type?: string;
  reason?: string;
  submitted_at?: string;
  grant_expires_at?: string | null;
  decided_at?: string | null;
  decision_comment?: string | null;
}

export interface PortalApprovalApplicant {
  user_id?: string;
  name?: string;
  email?: string;
  department?: string;
}

/** 门户「待我审批」条目: 对齐后端 /portal/api/v1/me/approvals 序列化字段。 */
export interface PortalApprovalItem {
  id: number;
  app_key?: string;
  app_name?: string;
  request_type?: string;
  status?: string;
  status_label?: string;
  grant_type?: string;
  grant_expires_at?: string | null;
  reason?: string;
  submitted_at?: string;
  authorization_groups?: PermissionQueryGroupItem[];
  direct_grants?: PortalDirectGrantItem[];
  decided_at?: string | null;
  decision_comment?: string | null;
  applicant?: PortalApprovalApplicant;
  approver_user_ids?: string[];
  decided_by?: string | null;
}

export interface PortalCatalogApp {
  id: number;
  app_key: string;
  name: string;
  description?: string;
}

/** 历史兼容类型：门户 catalog 应使用 PortalCatalogAuthorizationGroup。 */
export interface PortalCatalogRole {
  id: number;
  app_key: string;
  key: string;
  name: string;
  description?: string;
  requestable?: boolean;
  requires_approval?: boolean;
}

export interface PortalCatalogAuthorizationGroup {
  id: number;
  app_key: string;
  key: string;
  kind: "role" | "bundle" | string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  requestable?: boolean;
  requires_approval?: boolean;
}

export interface DirectGrantScopeOption {
  app_key?: string;
  permission: string;
  scope: string;
  name?: string;
  name_en?: string;
  description?: string;
  description_en?: string;
}

export interface PortalRequestCatalog {
  apps?: PortalCatalogApp[];
  authorization_groups?: PortalCatalogAuthorizationGroup[];
  direct_grant_scope_options?: DirectGrantScopeOption[];
  permission_groups?: PermissionGroupItem[];
  ungrouped_permissions?: PermissionItem[];
  catalog_version?: number;
  snapshot_version?: string;
}

/** 审批模板: 对齐后端 approval_templates_api._template_item 序列化字段。app_key 为空串表示平台共用模板。 */
export interface ApprovalTemplateItem {
  id: number;
  app_key: string;
  key: string;
  name: string;
  dingtalk_process_code: string;
  form_schema?: JsonObject;
  form_mapping?: JsonObject;
  is_active: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ApprovalTemplateTestResult {
  instance_id: string;
  status: string;
  dingtalk_process_instance_id: string;
}

/** 审批实例运营行: 对齐后端 approval_instances_api._instance_item 序列化字段。 */
export interface ApprovalInstanceRow {
  instance_id: string;
  app_key: string;
  template_key: string;
  biz_key: string;
  status: "created" | "submitted" | "approved" | "rejected" | "canceled" | "failed" | string;
  originator_user_id: string;
  dingtalk_process_instance_id: string;
  delivery_state: "" | "pending" | "delivered" | "failed" | "skipped" | string;
  delivery_attempts: number;
  delivery_last_error: string;
  last_error: string;
  created_at: string;
  completed_at: string | null;
}

/** 应用 Webhook 配置: secret 明文只在轮换/首次保存的 PUT 响应中出现一次。 */
export interface WebhookConfigItem {
  enabled: boolean;
  secret_configured: boolean;
  approval_callback_url: string;
  handover_url: string;
  onboard_url: string;
  updated_by?: string;
  updated_at?: string | null;
  secret?: string;
}

export interface WebhookConfigPayload {
  webhook_config: WebhookConfigItem | null;
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
  // 审计日志(audit-logs)行字段: 与后端 audit_api._audit_item 序列化器一一对应, 审计行无 id。
  actor_type?: string;
  actor_id?: string;
  event_type?: string;
  target_type?: string;
  target_id?: string;
  metadata?: JsonObject | null;
  created_at?: string | null;
}
