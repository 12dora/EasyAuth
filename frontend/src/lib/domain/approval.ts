/** 本模块定义审批模板与审批实例领域契约。 */

import type { JsonValue } from "./common";
import { bindParse } from "./parse";
import { ACCOUNT_KINDS, type AccountKind } from "./person";

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
  app_name: string;
  /** 管理员维护的应用别名; 没配别名时是空串。 */
  app_alias: string;
  template_key: string;
  biz_key: string;
  status: "created" | "submitted" | "approved" | "rejected" | "canceled" | "failed" | string;
  originator_user_id: string;
  /** 发起人显示名; 目录里没有姓名时为空串, 此时界面回落展示 originator_user_id。 */
  originator_name: string;
  /** 发起人部门路径; 未同步或本地账号时缺省/空串。 */
  originator_department?: string;
  originator_account_kind: AccountKind;
  /** 发起人头像 URL; 无照片时为空串。 */
  originator_avatar_url: string;
  dingtalk_process_instance_id: string;
  delivery_state: "" | "pending" | "delivered" | "failed" | "skipped" | string;
  delivery_attempts: number;
  delivery_last_error: string;
  last_error: string;
  created_at: string;
  completed_at: string | null;
}

export class ApprovalInstanceContractError extends Error {
  constructor(field: string) {
    super(`审批实例契约违约: ${field}`);
    this.name = "ApprovalInstanceContractError";
  }
}

const {
  requireRecord,
  requireString,
  requireEnum,
  optionalPresentString,
} = bindParse({ fail: (path) => new ApprovalInstanceContractError(path) });

/** 审批实例行: originator_account_kind 必填, 缺失或非法值立即失败。 */
export function parseApprovalInstanceRow(raw: JsonValue): ApprovalInstanceRow {
  const source = requireRecord(raw, "row");
  return {
    ...(source as unknown as ApprovalInstanceRow),
    originator_account_kind: requireEnum(source.originator_account_kind, "originator_account_kind", ACCOUNT_KINDS),
    originator_department: optionalPresentString(source.originator_department, "originator_department"),
    originator_avatar_url: requireString(source.originator_avatar_url, "originator_avatar_url"),
  };
}

