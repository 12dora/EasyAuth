/** 本模块定义 Operations 与 Audit 领域契约。 */

import type { JsonObject } from "./common";

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

