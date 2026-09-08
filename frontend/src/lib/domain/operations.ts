/** 本模块定义 Operations 与 Audit 领域契约。 */

import type { JsonObject } from "./common";

/** 访问申请的审批人: 后端在 id 之外一并下发姓名, 界面一律按姓名展示。 */
export interface OperationApprover {
  user_id: string;
  name: string;
}

export interface OperationRow {
  id?: number;
  user_id?: string;
  /** 用户显示名; 目录里没有姓名时为空串, 此时界面回落展示 user_id。 */
  user_name?: string;
  app_key?: string;
  app_name?: string;
  app_alias?: string;
  status?: string;
  request_type?: string;
  reason?: string;
  submitted_at?: string;
  approvers?: OperationApprover[];
  /** 决定人显示名; 尚未决定时为空串。 */
  decided_by_name?: string;
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
