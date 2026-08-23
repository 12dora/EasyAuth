import type { JsonObject } from "../../lib/api";
import type { ApprovalFormFieldType, ApprovalFormSchema, ApprovalTemplateItem } from "../../lib/domain";

export const TEMPLATES_QUERY_KEY = ["console", "approval-templates"];
export const TEMPLATE_MUTATION_SCOPE = { id: "console-approval-templates" };

export interface ApprovalTemplatePayload {
  approval_template: ApprovalTemplateItem;
}

export interface TemplateFormPayload {
  app_key: string;
  key: string;
  name: string;
  dingtalk_process_code: string;
  form_schema: ApprovalFormSchema;
  form_mapping: Record<string, string>;
  is_active: boolean;
}

/** 校验文本为 JSON 对象(空文本视为 {}); 失败返回 null。 */
export function parseJsonObject(text: string): JsonObject | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return {};
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as JsonObject;
    }
  } catch {
    return null;
  }
  return null;
}

const APPROVAL_FORM_FIELD_TYPES: ReadonlySet<ApprovalFormFieldType> = new Set([
  "string",
  "integer",
  "number",
  "boolean",
]);

/** 单个字段定义只允许 type/required 两个键, type 必须是受支持的字段类型。 */
function isValidFieldDefinition(definitionValue: unknown): boolean {
  if (typeof definitionValue !== "object" || definitionValue === null || Array.isArray(definitionValue)) {
    return false;
  }
  const definition = definitionValue as Record<string, unknown>;
  return !(
    Object.keys(definition).some((key) => key !== "type" && key !== "required") ||
    typeof definition.type !== "string" ||
    !APPROVAL_FORM_FIELD_TYPES.has(definition.type as ApprovalFormFieldType) ||
    (definition.required !== undefined && typeof definition.required !== "boolean")
  );
}

/** 校验审批表单 schema 契约(空文本视为 {}); 失败返回 null。 */
export function parseFormSchema(text: string): ApprovalFormSchema | null {
  const parsed = parseJsonObject(text);
  if (parsed === null) {
    return null;
  }
  for (const [fieldName, definitionValue] of Object.entries(parsed)) {
    if (fieldName.trim() === "" || !isValidFieldDefinition(definitionValue)) {
      return null;
    }
  }
  return parsed as unknown as ApprovalFormSchema;
}

/** 校验 mapping 严格引用 schema 字段且控件名非空(空文本视为 {}); 失败返回 null。 */
export function parseStringMapping(text: string, schema: ApprovalFormSchema): Record<string, string> | null {
  const parsed = parseJsonObject(text);
  if (parsed === null) {
    return null;
  }
  const entries = Object.entries(parsed);
  if (
    !entries.every(
      ([fieldName, componentName]) =>
        fieldName.trim() !== "" &&
        Object.hasOwn(schema, fieldName) &&
        typeof componentName === "string" &&
        componentName.trim() !== "",
    )
  ) {
    return null;
  }
  return Object.fromEntries(entries.map(([fieldName, componentName]) => [fieldName, (componentName as string).trim()]));
}

export function formatJsonObject(value: object | undefined): string {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

/** PATCH 契约不接受 app_key/key(作用域与标识创建后不可改), 只提交可变字段。 */
export function templatePatchBody(payload: TemplateFormPayload): JsonObject {
  return {
    name: payload.name,
    dingtalk_process_code: payload.dingtalk_process_code,
    form_schema: payload.form_schema as unknown as JsonObject,
    form_mapping: payload.form_mapping,
    is_active: payload.is_active,
  } satisfies JsonObject;
}

export function templateCreateBody(payload: TemplateFormPayload): JsonObject {
  return {
    ...payload,
    form_schema: payload.form_schema as unknown as JsonObject,
  } satisfies JsonObject;
}

export interface TemplateFormState {
  appKey: string;
  key: string;
  name: string;
  processCode: string;
  formSchemaText: string;
  formMappingText: string;
  isActive: boolean;
}

const BLANK_TEMPLATE_FORM: TemplateFormState = {
  appKey: "",
  key: "",
  name: "",
  processCode: "",
  formSchemaText: "",
  formMappingText: "",
  isActive: true,
};

/** 编辑弹窗的初始表单值: 新建时全空, 编辑时回填模板。 */
export function initialTemplateForm(template: ApprovalTemplateItem | null): TemplateFormState {
  if (!template) {
    return BLANK_TEMPLATE_FORM;
  }
  return {
    appKey: template.app_key,
    key: template.key,
    name: template.name,
    processCode: template.dingtalk_process_code,
    formSchemaText: formatJsonObject(template.form_schema),
    formMappingText: formatJsonObject(template.form_mapping),
    isActive: template.is_active,
  };
}

export type TemplateFormValidation =
  | { ok: true; formSchema: ApprovalFormSchema; formMapping: Record<string, string> }
  | { ok: false; invalid: "schema" | "mapping" };

/** schema 先于 mapping 校验: mapping 必须引用已通过校验的 schema 字段。 */
export function validateTemplateForm(formSchemaText: string, formMappingText: string): TemplateFormValidation {
  const formSchema = parseFormSchema(formSchemaText);
  if (formSchema === null) {
    return { ok: false, invalid: "schema" };
  }
  const formMapping = parseStringMapping(formMappingText, formSchema);
  if (formMapping === null) {
    return { ok: false, invalid: "mapping" };
  }
  return { ok: true, formSchema, formMapping };
}

export type TemplateTestValidation =
  | { ok: true; body: JsonObject }
  | { ok: false; originatorMissing: boolean; appKeyMissing: boolean; formInvalid: boolean };

/** 试跑表单一次性校验三项, 三个错误同时回给调用方展示。 */
export function validateTemplateTest(input: {
  originatorUserId: string;
  appKey: string;
  formText: string;
  isPlatformTemplate: boolean;
}): TemplateTestValidation {
  const originatorMissing = input.originatorUserId.trim() === "";
  const appKeyMissing = input.isPlatformTemplate && input.appKey.trim() === "";
  const form = parseJsonObject(input.formText);
  if (originatorMissing || appKeyMissing || form === null) {
    return { ok: false, originatorMissing, appKeyMissing, formInvalid: form === null };
  }
  return {
    ok: true,
    body: {
      originator_user_id: input.originatorUserId.trim(),
      ...(input.isPlatformTemplate ? { app_key: input.appKey.trim() } : {}),
      ...(Object.keys(form).length > 0 ? { form } : {}),
    },
  };
}
