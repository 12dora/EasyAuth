export const zhCN = {
  "approvalTemplates.description": "维护钉钉审批流程模板：绑定 process_code、配置表单映射，并可发起测试审批验证配置。",

  "approvalTemplates.loadFailed": "审批模板加载失败",

  "approvalTemplates.saveFailed": "审批模板保存失败",

  "approvalTemplates.deleteTitle": "删除审批模板",

  "approvalTemplates.deleteMessage": "确定删除审批模板「{name}」吗？该操作不可恢复。",

  "approvalTemplates.deleteSuccess": "审批模板已删除",

  "approvalTemplates.deleteFailed": "删除审批模板失败",

  "approvalTemplates.empty.title": "暂无审批模板",
  "approvalTemplates.empty.description": "新建模板并绑定钉钉流程码后，应用即可通过 EasyAuth 发起钉钉审批。",

  "approvalTemplates.create": "新建模板",

  "approvalTemplates.column.key": "模板 Key",
  "approvalTemplates.column.app": "所属应用",

  "approvalTemplates.platformShared": "平台共用",

  "approvalTemplates.createTitle": "新建审批模板",

  "approvalTemplates.editTitle": "编辑审批模板",

  "approvalTemplates.field.appKey": "所属应用 app_key",
  "approvalTemplates.field.appKeyHint": "留空表示平台共用模板；创建后不可修改。",
  "approvalTemplates.field.key": "模板 Key",
  "approvalTemplates.field.keyHint": "应用侧发起审批时使用的模板标识；创建后不可修改。",
  "approvalTemplates.field.processCode": "钉钉流程码（process_code）",
  "approvalTemplates.field.formSchema": "表单结构（form_schema，JSON）",
  "approvalTemplates.field.formSchemaHint": "字段定义仅支持 type（string、integer、number、boolean）和可选布尔 required；留空表示不接收表单字段。",
  "approvalTemplates.field.formMapping": "表单映射（form_mapping，JSON）",
  "approvalTemplates.field.formMappingHint": "将 form_schema 中的字段映射到非空钉钉表单控件名；未映射字段使用原字段名。",
  "approvalTemplates.field.isActive": "启用该模板",

  "approvalTemplates.invalidJson": "不是合法的 JSON 对象，请检查后重试。",

  "approvalTemplates.invalidFormSchema": "form_schema 不符合字段契约，请检查字段名、type 和 required。",

  "approvalTemplates.invalidFormMapping": "form_mapping 必须只引用 form_schema 字段，且控件名必须为非空字符串。",

  "approvalTemplates.test.action": "发起测试审批",
  "approvalTemplates.test.description": "将以所选发起人的身份在钉钉真实创建一条审批实例，用于验证流程码与表单映射配置。",
  "approvalTemplates.test.originator": "发起人",
  "approvalTemplates.test.originatorRequired": "请选择发起人",
  "approvalTemplates.test.appKey": "发起应用 app_key",
  "approvalTemplates.test.appKeyHint": "平台共用模板必须指定以哪个应用身份发起。",
  "approvalTemplates.test.appKeyRequired": "平台共用模板需填写发起应用 app_key",
  "approvalTemplates.test.form": "表单数据（form，JSON，可选）",
  "approvalTemplates.test.submit": "发起测试",
  "approvalTemplates.test.failed": "测试审批发起失败",
  "approvalTemplates.test.success": "测试审批已发起",
  "approvalTemplates.test.instanceId": "实例 ID",
  "approvalTemplates.test.dingtalkInstanceId": "钉钉实例号",

  "approvalInstances.description": "观测钉钉审批实例与结果回投状态，投递失败的实例可在这里重新投递。",

  "approvalInstances.column.app": "发起应用",
  "approvalInstances.column.template": "模板",
  "approvalInstances.column.bizKey": "业务单号",
  "approvalInstances.column.originator": "发起人",
  "approvalInstances.column.dingtalkInstance": "钉钉实例号",
  "approvalInstances.column.delivery": "投递状态",
  "approvalInstances.column.createdAt": "发起时间",

  "approvalInstances.status.created": "已创建",
  "approvalInstances.status.submitted": "审批中",
  "approvalInstances.status.approved": "已通过",
  "approvalInstances.status.rejected": "已拒绝",
  "approvalInstances.status.canceled": "已撤销",
  "approvalInstances.status.failed": "失败",

  "approvalInstances.delivery.pending": "待投递",
  "approvalInstances.delivery.delivered": "已投递",
  "approvalInstances.delivery.failed": "投递失败",
  "approvalInstances.delivery.skipped": "未配置推送",

  "approvalInstances.redeliver": "重新投递",

  "approvalInstances.redelivered": "已重新投递",

  "approvalInstances.redeliverFailed": "重新投递失败",

  "approvals.approve": "同意",

  "approvals.reject": "驳回",

  "approvals.approveTitle": "同意申请",

  "approvals.rejectTitle": "驳回申请",

  "approvals.approveConfirm": "确认同意",

  "approvals.rejectConfirm": "确认驳回",

  "approvals.comment": "审批意见",

  "approvals.commentOptionalHint": "选填，审批意见会展示给申请人。",

  "approvals.commentRequiredHint": "必填，驳回理由会展示给申请人。",

  "approvals.commentRequired": "请填写驳回意见",

  "approvals.conflict": "该申请已被其他审批人处理",

  "approvals.resubmitRequired": "授权事实已变化，请重新提交申请",

  "approvals.approved": "授权已生效",

  "approvals.rejected": "申请已驳回",

  "approvals.approveFailed": "同意操作失败",

  "approvals.rejectFailed": "驳回操作失败",

  "approvals.grantFailedCommitted": "审批已通过，但授权未落地",

  "approvals.grantFailedCommittedDescription": "审批决定已提交，申请已进入授权失败状态，请联系管理员重试授权落地。",
} as const;

export const en: Record<keyof typeof zhCN, string> = {
  "approvalTemplates.description": "Maintain DingTalk approval flow templates: bind a process_code, configure the form mapping, and start a test approval to verify the setup.",

  "approvalTemplates.loadFailed": "Failed to load approval templates",

  "approvalTemplates.saveFailed": "Failed to save the approval template",

  "approvalTemplates.deleteTitle": "Delete approval template",

  "approvalTemplates.deleteMessage": "Delete approval template “{name}”? This cannot be undone.",

  "approvalTemplates.deleteSuccess": "Approval template deleted",

  "approvalTemplates.deleteFailed": "Failed to delete the approval template",

  "approvalTemplates.empty.title": "No approval templates",
  "approvalTemplates.empty.description": "Create a template bound to a DingTalk process code so applications can start DingTalk approvals through EasyAuth.",

  "approvalTemplates.create": "Create Template",

  "approvalTemplates.column.key": "Template Key",
  "approvalTemplates.column.app": "Application",

  "approvalTemplates.platformShared": "Platform-shared",

  "approvalTemplates.createTitle": "Create approval template",

  "approvalTemplates.editTitle": "Edit approval template",

  "approvalTemplates.field.appKey": "Application app_key",
  "approvalTemplates.field.appKeyHint": "Leave empty for a platform-shared template; cannot be changed after creation.",
  "approvalTemplates.field.key": "Template key",
  "approvalTemplates.field.keyHint": "The template identifier applications use to start approvals; cannot be changed after creation.",
  "approvalTemplates.field.processCode": "DingTalk process code (process_code)",
  "approvalTemplates.field.formSchema": "Form schema (form_schema, JSON)",
  "approvalTemplates.field.formSchemaHint": "Field definitions only support type (string, integer, number, or boolean) and optional boolean required. Leave empty to accept no form fields.",
  "approvalTemplates.field.formMapping": "Form mapping (form_mapping, JSON)",
  "approvalTemplates.field.formMappingHint": "Map form_schema fields to non-empty DingTalk form control names. Unmapped fields use their original names.",
  "approvalTemplates.field.isActive": "Enable this template",

  "approvalTemplates.invalidJson": "Not a valid JSON object; please check and retry.",

  "approvalTemplates.invalidFormSchema": "form_schema does not match the field contract. Check field names, type, and required.",

  "approvalTemplates.invalidFormMapping": "form_mapping may only reference form_schema fields, with non-empty string control names.",

  "approvalTemplates.test.action": "Start test approval",
  "approvalTemplates.test.description": "Creates a real DingTalk approval instance as the selected originator to verify the process code and form mapping configuration.",
  "approvalTemplates.test.originator": "Originator",
  "approvalTemplates.test.originatorRequired": "Please select an originator",
  "approvalTemplates.test.appKey": "Originating app_key",
  "approvalTemplates.test.appKeyHint": "Platform-shared templates must specify which application starts the approval.",
  "approvalTemplates.test.appKeyRequired": "Platform-shared templates require an originating app_key",
  "approvalTemplates.test.form": "Form data (form, JSON, optional)",
  "approvalTemplates.test.submit": "Start test",
  "approvalTemplates.test.failed": "Failed to start the test approval",
  "approvalTemplates.test.success": "Test approval started",
  "approvalTemplates.test.instanceId": "Instance ID",
  "approvalTemplates.test.dingtalkInstanceId": "DingTalk instance ID",

  "approvalInstances.description": "Observe DingTalk approval instances and result delivery; failed deliveries can be retried here.",

  "approvalInstances.column.app": "Application",
  "approvalInstances.column.template": "Template",
  "approvalInstances.column.bizKey": "Business key",
  "approvalInstances.column.originator": "Originator",
  "approvalInstances.column.dingtalkInstance": "DingTalk instance ID",
  "approvalInstances.column.delivery": "Delivery",
  "approvalInstances.column.createdAt": "Started at",

  "approvalInstances.status.created": "Created",
  "approvalInstances.status.submitted": "In review",
  "approvalInstances.status.approved": "Approved",
  "approvalInstances.status.rejected": "Rejected",
  "approvalInstances.status.canceled": "Canceled",
  "approvalInstances.status.failed": "Failed",

  "approvalInstances.delivery.pending": "Pending",
  "approvalInstances.delivery.delivered": "Delivered",
  "approvalInstances.delivery.failed": "Delivery failed",
  "approvalInstances.delivery.skipped": "No webhook configured",

  "approvalInstances.redeliver": "Redeliver",

  "approvalInstances.redelivered": "Redelivered",

  "approvalInstances.redeliverFailed": "Failed to redeliver",

  "approvals.approve": "Approve",

  "approvals.reject": "Reject",

  "approvals.approveTitle": "Approve request",

  "approvals.rejectTitle": "Reject request",

  "approvals.approveConfirm": "Confirm approval",

  "approvals.rejectConfirm": "Confirm rejection",

  "approvals.comment": "Decision comment",

  "approvals.commentOptionalHint": "Optional; the applicant can see this comment.",

  "approvals.commentRequiredHint": "Required; the applicant can see the rejection reason.",

  "approvals.commentRequired": "Please provide a rejection reason",

  "approvals.conflict": "This request has already been handled by another approver",

  "approvals.resubmitRequired": "Access facts changed. Submit a new request.",

  "approvals.approved": "Access granted",

  "approvals.rejected": "Request rejected",

  "approvals.approveFailed": "Failed to approve",

  "approvals.rejectFailed": "Failed to reject",

  "approvals.grantFailedCommitted": "Approved, but access was not applied",

  "approvals.grantFailedCommittedDescription": "The decision was committed and the request is now in grant-failed state. Contact an administrator to retry applying access.",
};
