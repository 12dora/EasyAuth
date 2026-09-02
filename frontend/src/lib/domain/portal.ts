/** 本模块定义 Portal 访问请求与审批视图领域契约。 */

import type {
  AuthorizationGroupKind,
  ExpandedGrantItem,
  PermissionGroupItem,
  PermissionItem,
  PermissionQueryGroupItem,
} from "./app";

export interface PortalGrant {
  grant_id?: number;
  grant_revision?: number;
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

/** 申请行上的审批人: 仅 user_id + name, 与后端 `approver_option` 一致。 */
export interface PortalRequestApprover {
  user_id: string;
  name: string;
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
  base_grant_id?: number | null;
  base_grant_revision?: number | null;
  grant_type?: string;
  reason?: string;
  submitted_at?: string;
  grant_expires_at?: string | null;
  /** 仅 status 为 submitted 时非空: 当前待处理的审批人分配。 */
  current_approvers?: PortalRequestApprover[];
  /** 决定人 actor id; 未决或已撤回时为空字符串。 */
  decided_by?: string;
  /** 决定人身份: user / console_admin; 未决或已撤回时为空字符串。 */
  decision_actor_type?: string;
  /** 决定人显示名; 后端解析不出姓名时为 null(此时只能回退展示 decided_by)。 */
  decided_by_name?: string | null;
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
  base_grant_id?: number | null;
  base_grant_revision?: number | null;
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

export interface PortalCatalogAuthorizationGroup {
  id: number;
  app_key: string;
  key: string;
  kind: AuthorizationGroupKind;
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

