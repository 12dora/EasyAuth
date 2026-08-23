/** 本模块定义审批模板与审批实例领域契约。 */

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

