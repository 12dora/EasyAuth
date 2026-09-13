/** 本模块定义 Operations 与 Audit 领域契约。 */

import type { JsonObject, JsonValue } from "./common";
import { bindParse, parseNullablePersonRef as parseSharedNullablePersonRef, parsePersonRef as parseSharedPersonRef } from "./parse";
import { ACCOUNT_KINDS, type AccountKind, type PersonRef } from "./person";

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

const {
  requireRecord,
  requireString,
  requireArray,
  requireEnum,
  optionalPresentString,
} = bindParse({ fail: (path) => new OperationContractError(path) });

/** 审批人必须带 account_kind; 缺失或非法值立即失败。 */
export function parseOperationApprover(raw: unknown, field = "approver"): OperationApprover {
  const source = requireRecord(raw, field);
  return {
    user_id: requireString(source.user_id, `${field}.user_id`),
    name: requireString(source.name, `${field}.name`),
    department: optionalPresentString(source.department, `${field}.department`),
    account_kind: requireEnum(source.account_kind, `${field}.account_kind`, ACCOUNT_KINDS),
  };
}

/** 访问申请行: 审批人数组必填, 每人走 parseOperationApprover。 */
export function parseOperationAccessRequestRow(raw: JsonValue): OperationRow {
  const source = requireRecord(raw, "row");
  return {
    ...(source as OperationRow),
    approvers: requireArray(source.approvers, "approvers").map((item, index) =>
      parseOperationApprover(item, `approvers[${index}]`),
    ),
  };
}

/** 人员对象; 字段与 `PersonRef` 一一对应, 缺任一字段即契约违约。 */
export function parsePersonRef(raw: unknown, field = "person"): PersonRef {
  return parseSharedPersonRef(raw, field, { fail: (path) => new OperationContractError(path) });
}

/** null 表示系统 / 未解析到 UserMirror; 缺字段或非法值立即失败。 */
export function parseNullablePersonRef(raw: unknown, field: string): PersonRef | null {
  return parseSharedNullablePersonRef(raw, field, { fail: (path) => new OperationContractError(path) });
}

/** 审计日志行: `actor_person` 必填(可为 null)。 */
export function parseAuditLogRow(raw: JsonValue): OperationRow {
  const source = requireRecord(raw, "row");
  if (!Object.prototype.hasOwnProperty.call(source, "actor_person")) {
    throw new OperationContractError("actor_person");
  }
  return {
    ...(source as OperationRow),
    actor_person: parseNullablePersonRef(source.actor_person, "actor_person"),
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
  /** 用户头像 URL; 无照片时为空串。 */
  user_avatar_url?: string;
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
  /** 操作者人员对象; 审计行必填, 解析不到 UserMirror 时为 null。 */
  actor_person?: PersonRef | null;
  event_type?: string;
  target_type?: string;
  target_id?: string;
  metadata?: JsonObject | null;
  created_at?: string | null;
}
