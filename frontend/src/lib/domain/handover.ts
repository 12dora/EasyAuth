/** 本模块定义 Lifecycle、Handover 与 Onboarding 领域契约。 */

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

/** 数据交接 v2: 严格对齐 docs/design/data-handover-v2/01-easyauth-backend.md §6.2 */
export type HandoverKind = "offboard" | "transfer" | "pre_offboard" | "reassign";
export type HandoverTaskStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type HandoverAssigneeState = "manager" | "subject" | "superuser_pool";
export type HandoverActionStatus =
  | "pending"
  | "previewed"
  | "executing"
  | "async_pending"
  | "done"
  | "failed"
  | "skipped"
  | "blocked"
  | "async_attention_required";

export interface HandoverUserRef {
  user_id: string;
  name: string;
  department?: string;
  status?: "active" | "disabled" | "departed";
}

export interface HandoverSubject {
  user_id: string;
  name: string;
  email: string;
  department: string;
  status: string;
}

export type HandoverAssetAction = "transfer" | "release" | "skip";

export interface HandoverAssetType {
  type: string;
  label: string;
  count: number;
  detail_supported: boolean;
  releasable: boolean;
  default_action: HandoverAssetAction;
  default_to_user: HandoverUserRef | null;
  override_count: number;
}

export interface HandoverAssetSummary {
  transferred: number;
  released: number;
  skipped: number;
  merged: number;
  failed: number;
}

export type HandoverAllowedAction = "preview" | "execute" | "retry" | "skip";

export interface HandoverBatchProgress {
  completed: number;
  total: number;
  current_batch_seq: number;
}

export interface HandoverSkipRecord {
  generation: number;
  actor_id: string;
  reason: string;
  skipped_at: string;
}

export interface HandoverAction {
  app_key: string;
  app_name: string;
  status: HandoverActionStatus;
  blocked_reason: string;
  skip_reason: string;
  /** 强行跳过的责任链(当前轮次); 升级时会被清空, 展示要优先读 skip_history */
  skipped_by: string;
  skipped_at: string | null;
  /** 跨轮次永久的强跳记录 */
  skip_history: HandoverSkipRecord[];
  last_error: string;
  /** 后端算好的可用操作; 前端不得解析 last_error 猜可不可重试 */
  allowed_actions: HandoverAllowedAction[];
  confirm_version: number;
  overrides_version: number;
  batch_progress: HandoverBatchProgress | null;
  asset_types: HandoverAssetType[];
  approval_instance_warning: { message: string; link: string; recorded_at: string } | null;
  /** 仅 kind=offboard 有意义; null = 只撤权不转授 */
  grant_receiver: HandoverUserRef | null;
  /** done 之后才有; 按 asset_type 分组的五元统计 */
  summary: Record<string, HandoverAssetSummary> | null;
  /** 非 null = 数据已落地、权限尚未转授 */
  data_completed_at: string | null;
}

export interface HandoverDeferRecord {
  escalation_level: number;
  actor_id: string;
  at: string;
  reason: string;
}

export interface HandoverEscalation {
  deadline: string | null;
  days_left: number | null;
  level: number;
  defer_history: HandoverDeferRecord[];
  deferred_at: string | null;
}

export interface HandoverAssetItem {
  id: string;
  label: string;
  hint: string;
}

export interface HandoverAssetItemsPage {
  items: HandoverAssetItem[];
  page: number;
  page_size: number;
  total: number;
  unfiltered_total: number | null;
  stale: boolean;
}

export interface HandoverOverrideEntry {
  asset_id: string;
  action: HandoverAssetAction;
  to_user_id?: string | null;
  to_user?: HandoverUserRef | null;
  label: string;
}

export interface HandoverOverridesPayload {
  overrides_version: number;
  overrides: HandoverOverrideEntry[];
}

export interface HandoverCandidate {
  user_id: string;
  name: string;
  department?: string;
}

export type HandoverCapabilityState = "declared" | "none" | "undeclared";

export interface HandoverCapabilityPayload {
  handover_capability: HandoverCapabilityState;
  handover_asset_types: Array<{
    type: string;
    label: string;
    detail_supported: boolean;
    releasable: boolean;
  }>;
  handover_url: string;
  declared_by: string;
  declared_at: string | null;
  synced_at: string | null;
}

export interface HandoverBlockedAppsPayload {
  app_count: number;
  task_count: number;
  apps: Array<{ app_key: string; app_name: string; blocked_task_count: number }>;
}

/** 门户/控制台列表行: 详情去掉 actions/team_items，另加计数。 */
export interface HandoverTaskListItem {
  id: number;
  kind: HandoverKind;
  status: HandoverTaskStatus;
  generation: number;
  subject: HandoverUserRef & { email?: string };
  assignee: HandoverUserRef | null;
  assignee_state: HandoverAssigneeState;
  escalation_level: number;
  escalation: HandoverEscalation;
  reason: string;
  created_at: string;
  pending_app_count: number;
  blocked_app_count: number;
  total_asset_count: number;
  created_by?: string;
  allowed_actions?: string[];
  updated_at?: string;
}

/** 控制台列表行别名（保留既有命名）。 */
export type HandoverTaskRow = HandoverTaskListItem;

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
  app_key?: string;
  kind?: "group" | "permission" | string;
  target_key?: string;
  name?: string;
  scope_key?: string;
  grant_type?: string;
  grant_expires_at?: string | null;
  duration_days?: number | null;
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
  template_revision_id?: number | null;
  template_revision?: number | null;
  grant_diff: TransferGrantDiff;
  revision: number;
  confirmed_at: string | null;
}

export interface HandoverTaskDetail {
  id: number;
  kind: HandoverKind;
  status: HandoverTaskStatus;
  generation: number;
  subject: HandoverUserRef & { email?: string };
  assignee: HandoverUserRef | null;
  assignee_state: HandoverAssigneeState;
  escalation_level: number;
  escalation: HandoverEscalation;
  reason: string;
  created_at: string;
  actions: HandoverAction[];
  team_items: HandoverTeamItemRow[];
  transfer_plan?: TransferPlanItem | null;
  created_by?: string;
  allowed_actions?: string[];
  updated_at?: string;
}

/** @deprecated 使用 HandoverTaskDetail；保留别名以免遗漏引用。 */
export type HandoverTaskDetailItem = HandoverTaskDetail;

export interface HandoverTaskPayload {
  handover_task?: HandoverTaskDetail;
}

export interface HandoverMeTasksPayload {
  handover_tasks: {
    as_assignee: HandoverTaskListItem[];
    as_subject: HandoverTaskListItem[];
  };
}

export interface HandoverActionPayload {
  action: HandoverAction;
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
  current_revision_id?: number | null;
  current_revision?: number | null;
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

