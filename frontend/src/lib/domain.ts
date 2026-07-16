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

export interface PortalGrant {
  app_key?: string;
  app_name?: string;
  groups?: PermissionQueryGroupItem[];
  grants?: ExpandedGrantItem[];
  grant_version?: number;
  catalog_version?: number;
  snapshot_version?: string;
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

export type ApprovalFormFieldType = "string" | "integer" | "number" | "boolean";

export interface ApprovalFormFieldDefinition {
  type: ApprovalFormFieldType;
  required?: boolean;
}

export type ApprovalFormSchema = Record<string, ApprovalFormFieldDefinition>;

/** 审批模板: 对齐后端 approval_templates_api._template_item 序列化字段。app_key 为空串表示平台共用模板。 */
export interface ApprovalTemplateItem {
  id: number;
  app_key: string;
  key: string;
  name: string;
  dingtalk_process_code: string;
  form_schema: ApprovalFormSchema;
  form_mapping: Record<string, string>;
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

/** 出站供给连接器 config_schema 的字段描述(JSON Schema 子集, x-secret 标记加密字段)。 */
export interface ConnectorSchemaProperty {
  type?: "string" | "boolean" | "number" | string;
  title?: string;
  description?: string;
  default?: string | number | boolean;
  enum?: Array<string | number>;
  "x-secret"?: boolean;
}

export interface ConnectorConfigSchema {
  type?: string;
  properties?: Record<string, ConnectorSchemaProperty>;
  required?: string[];
}

export interface ConnectorTypeItem {
  key: string;
  display_name: string;
  config_schema: ConnectorConfigSchema;
}

/** 连接器实例: config 中 x-secret 字段读接口恒为空串, configured_secrets 标记已配置。 */
export interface ConnectorInstanceItem {
  id: number;
  connector_key: string;
  display_name: string;
  enabled: boolean;
  config: JsonObject;
  configured_secrets: string[];
  reconcile_interval_seconds: number;
  last_reconcile_at: string | null;
  last_status: "" | "success" | "partial" | "failed" | string;
  last_error: string;
  consecutive_failures: number;
  updated_by: string;
  updated_at: string;
}

export interface ConnectorsPayload {
  connector_types: ConnectorTypeItem[];
  data: ConnectorInstanceItem[];
}

export interface ConnectorInstancePayload {
  connector: ConnectorInstanceItem;
}

export interface ConnectorTestResult {
  ok: boolean;
  message: string;
}

export interface ConnectorMappingItem {
  authorization_group_key: string;
  authorization_group_name: string;
  external_ref: string;
  auto_create: boolean;
}

export interface ConnectorExternalGroupItem {
  ref: string;
  name: string;
}

export interface ConnectorSyncRunItem {
  id: number;
  trigger: "periodic" | "event" | "manual" | "offboard" | string;
  status: "success" | "partial" | "failed" | string;
  started_at: string;
  finished_at: string;
  stats: Record<string, number>;
  error: string;
}

/** M4 生命周期: 人员列表行, 对齐后端 users_api._person_item 序列化字段。 */
export interface PersonRow {
  user_id: string;
  name: string;
  email: string;
  department: string;
  status: "active" | "disabled" | "departed" | string;
  open_handover_task_id: number | null;
  open_handover_kind: "offboard" | "transfer" | "";
}

export interface HandoverUserRef {
  user_id: string;
  name: string;
}

export interface HandoverSubject {
  user_id: string;
  name: string;
  email: string;
  department: string;
  status: string;
}

/** 交接单列表行: 对齐后端 lifecycle_api._task_item。 */
export interface HandoverTaskRow {
  id: number;
  kind: "offboard" | "transfer" | string;
  status: "pending" | "in_progress" | "completed" | "cancelled" | string;
  subject: HandoverSubject;
  reason: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** 应用交接项: 对齐后端 lifecycle_api._action_item。 */
export interface HandoverAppActionRow {
  id: number;
  app_key: string;
  app_name: string;
  status: "pending" | "previewed" | "executing" | "async_pending" | "done" | "failed" | "skipped" | string;
  to_user: HandoverUserRef | null;
  policy: JsonObject;
  preview_payload: JsonObject;
  result_payload: JsonObject;
  async_status_url: string;
  async_poll_attempts: number;
  attempts: number;
  last_error: string;
}

/** 团队交接项: 对齐后端 lifecycle_api._team_item。 */
export interface HandoverTeamItemRow {
  id: number;
  team_id: number;
  team_name: string;
  action: "pending" | "assign_leader" | "deactivate" | string;
  status: "pending" | "done" | "skipped" | string;
  to_user: HandoverUserRef | null;
}

export interface TransferGrantDiffEntry {
  key: string;
  selected?: boolean;
}

export interface TransferGrantDiff {
  revoke?: TransferGrantDiffEntry[];
  add?: TransferGrantDiffEntry[];
  keep?: TransferGrantDiffEntry[];
}

/** 转岗权限调整方案: 对齐后端 lifecycle_api._plan_item。 */
export interface TransferPlanItem {
  template_id: number | null;
  template_name: string;
  grant_diff: TransferGrantDiff;
  revision: number;
  confirmed_at: string | null;
}

export interface HandoverTaskDetailItem extends HandoverTaskRow {
  app_actions: HandoverAppActionRow[];
  team_items: HandoverTeamItemRow[];
  transfer_plan: TransferPlanItem | null;
}

export interface HandoverTaskPayload {
  handover_task?: HandoverTaskDetailItem;
}

/** 交接权限勾选项: 对齐后端 lifecycle_api._grant_item。 */
export interface HandoverGrantItemRow {
  id: number;
  app_key: string;
  kind: "group" | "permission" | string;
  key: string;
  name: string;
  scope_key: string;
  grant_type: string;
  grant_expires_at: string | null;
  selected: boolean;
  status: "pending" | "done" | "skipped" | string;
}

/** 岗位模板项(读取形态): 对齐后端 lifecycle_api._template_item 的 items 元素。 */
export interface OnboardingTemplateItemRow {
  id: number;
  app_key: string;
  kind: "group" | "permission" | string;
  key: string;
  name: string;
  scope_key: string;
  grant_type: string;
  duration_days: number | null;
}

export interface OnboardingTemplateRow {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
  items: OnboardingTemplateItemRow[];
  created_at?: string;
  updated_at?: string;
}

export interface OnboardingTemplatePayload {
  onboarding_template?: OnboardingTemplateRow;
}

export interface OnboardResult {
  user_id: string;
  template: string;
  granted_app_count: number;
}

export interface OperationRow {
  id?: number;
  user_id?: string;
  app_key?: string;
  status?: string;
  request_type?: string;
  reason?: string;
  submitted_at?: string;
  authorization_groups?: OperationAuthorizationGroup[];
  direct_grants?: OperationDirectGrant[];
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

export interface OperationAuthorizationGroup {
  key: string;
  kind: string;
  name: string;
  expires_at: string | null;
}

export interface OperationDirectGrant {
  permission: string;
  permission_name: string;
  scope: string;
  expires_at: string | null;
}
