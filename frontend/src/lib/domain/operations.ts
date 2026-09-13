/** 本模块定义 Operations 与 Audit 领域契约。 */

import type { JsonObject, JsonValue } from "./common";
import { isAccountKind, type AccountKind } from "./person";

/** 访问申请的审批人: 后端 `person_payload`, 界面一律按姓名展示。 */
export interface OperationApprover {
  user_id: string;
  name: string;
  department?: string;
  account_kind: AccountKind;
}

export class OperationContractError extends Error {
  constructor(field: string) {
    super(`运营申请契约违约: ${field}`);
    this.name = "OperationContractError";
  }
}

/** 审批人必须带 account_kind; 缺失或非法值立即失败。 */
export function parseOperationApprover(raw: JsonValue, field = "approver"): OperationApprover {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new OperationContractError(field);
  }
  const source = raw as JsonObject;
  const userId = source.user_id;
  const name = source.name;
  if (typeof userId !== "string") {
    throw new OperationContractError(`${field}.user_id`);
  }
  if (typeof name !== "string") {
    throw new OperationContractError(`${field}.name`);
  }
  if (!isAccountKind(source.account_kind)) {
    throw new OperationContractError(`${field}.account_kind`);
  }
  const department = source.department;
  if (department !== undefined && typeof department !== "string") {
    throw new OperationContractError(`${field}.department`);
  }
  return {
    user_id: userId,
    name,
    department,
    account_kind: source.account_kind,
  };
}

/** 访问申请行: 审批人数组必填, 每人走 parseOperationApprover。 */
export function parseOperationAccessRequestRow(raw: JsonValue): OperationRow {
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
    throw new OperationContractError("row");
  }
  const source = raw as JsonObject;
  const approvers = source.approvers;
  if (!Array.isArray(approvers)) {
    throw new OperationContractError("approvers");
  }
  return {
    ...(source as OperationRow),
    approvers: approvers.map((item, index) => parseOperationApprover(item, `approvers[${index}]`)),
  };
}

export interface OperationRow {
  id?: number;
  user_id?: string;
  /** 用户显示名; 目录里没有姓名时为空串, 此时界面回落展示 user_id。 */
  user_name?: string;
  /** 用户部门路径; 未同步或本地账号时缺省/空串。 */
  user_department?: string;
  user_account_kind?: AccountKind;
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
