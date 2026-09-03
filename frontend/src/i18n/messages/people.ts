export const zhCN = {
  "appList.eyebrow": "控制台",

  "appList.title": "应用列表",

  "appList.description": "查看可管理应用、配置完整性和接入入口。",

  "appList.onboardingWizard": "接入向导",

  "appList.quickCreate": "快速新建",

  "appList.loadFailed": "应用加载失败",

  "appList.column.app": "应用",
  "appList.column.owners": "负责人",
  "appList.column.configuration": "配置",

  "appList.empty.title": "暂无可见应用",
  "appList.empty.description": "当前账号暂无可管理或可查看的应用。",

  "appList.resumeOnboarding": "继续接入",

  "appList.createDialog.title": "新建应用",
  "appList.createDialog.name": "名称",
  "appList.createDialog.description": "描述",
  "appList.createDialog.ownerIds": "Owner 用户 ID",
  "appList.createDialog.developerIds": "Developer 用户 ID",
  "appList.createDialog.userIdsHint": "多个用户用逗号或换行分隔。",
  "appList.createDialog.failed": "创建失败",

  "appList.generateAppKey": "自动生成",

  "webhook.heading": "Webhook 推送",

  "webhook.description": "EasyAuth 会将审批结果回调、权限交接与入职事件以带签名的 POST 请求推送到以下地址，应用侧需用签名密钥验签后再处理事件。留空的 URL 不接收对应事件。",

  "webhook.loadFailed": "Webhook 配置加载失败",

  "webhook.saveFailed": "Webhook 配置保存失败",

  "webhook.saveSuccess": "Webhook 配置已保存",

  "webhook.notConfigured": "该应用尚未配置 Webhook；首次保存会自动生成签名密钥并展示一次，请妥善保存。",

  "webhook.enabled": "启用 Webhook 推送",

  "webhook.field.approvalCallbackUrl": "审批回调 URL（approval_callback_url）",
  "webhook.field.handoverUrl": "交接事件 URL（handover_url）",
  "webhook.field.onboardUrl": "入职事件 URL（onboard_url）",

  "webhook.secretLabel": "签名密钥",

  "webhook.secretConfigured": "已配置",

  "webhook.secretMissing": "未配置",

  "webhook.rotate": "生成/轮换密钥",

  "webhook.rotateTitle": "轮换签名密钥",

  "webhook.rotateMessage": "轮换后旧签名立即失效，请先让应用侧准备好更新密钥。确定继续？",

  "webhook.rotateConfirm": "确认轮换",

  "webhook.secretTitle": "Webhook 签名密钥（仅显示一次）",

  "webhook.sendTest": "发送测试事件",

  "webhook.testFailed": "测试事件发送失败",

  "webhook.testResult": "测试事件已入队：delivery_id {deliveryId}（状态 {status}）",

  "webhook.updatedMeta": "最近由 {user} 于 {time} 更新",

  "people.description": "查看全员在职状态，发起离职或转岗交接。",

  "people.loadFailed": "人员加载失败",

  "people.status.active": "在职",
  "people.status.disabled": "已停用",
  "people.status.departed": "已离职",

  "people.searchPlaceholder": "搜索姓名 / 邮箱 / 用户 ID",

  "people.column.name": "姓名",
  "people.column.department": "部门",
  "people.column.email": "邮箱",
  "people.column.consoleAdmin": "管理员",

  "people.consoleAdmin.yes": "是",

  "people.empty.title": "暂无人员",
  "people.empty.description": "当前筛选下没有可展示的人员。",

  "people.goHandover": "去交接",

  "people.startOffboard": "离职交接",

  "people.startTransfer": "转岗",

  "people.startDialog.offboardTitle": "发起离职交接",
  "people.startDialog.transferTitle": "发起转岗交接",
  "people.startDialog.offboardMessage": "将为「{name}」创建离职交接单。交接完成前，其数据保持原状，可以随时继续处理。",
  "people.startDialog.transferMessage": "将为「{name}」创建转岗交接单，可在交接单中调整数据归属、本人权限与团队。",
  "people.startDialog.reason": "备注原因",
  "people.startDialog.reasonHint": "选填，会记录在交接单上。",
  "people.startDialog.confirm": "创建交接单",

  "people.startFailed": "交接单创建失败",

  "people.permissions": "权限",

  "people.permissionsDialog.title": "配置权限",
  "people.permissionsDialog.message": "为「{name}」配置权限。目前仅可配置管理员身份，其余授权请在应用权限矩阵中处理。",
  "people.permissionsDialog.consoleAdmin": "管理员",
  "people.permissionsDialog.consoleAdminCheckbox": "设为管理员，可进入管理后台",
  "people.permissionsDialog.consoleAdminHint": "勾选后该人员门户右上角会出现「管理后台」入口，可进入控制台管理应用、权限与人员；取消勾选即收回该入口。",
  "people.permissionsDialog.failed": "权限保存失败",
} as const;

export const en: Record<keyof typeof zhCN, string> = {
  "appList.eyebrow": "Console",

  "appList.title": "Applications",

  "appList.description": "Review manageable apps, configuration readiness and onboarding entries.",

  "appList.onboardingWizard": "Onboarding Wizard",

  "appList.quickCreate": "Quick Create",

  "appList.loadFailed": "Failed to load applications",

  "appList.column.app": "Application",
  "appList.column.owners": "Owners",
  "appList.column.configuration": "Configuration",

  "appList.empty.title": "No visible applications",
  "appList.empty.description": "This account has no applications to manage or view yet.",

  "appList.resumeOnboarding": "Resume onboarding",

  "appList.createDialog.title": "Create Application",
  "appList.createDialog.name": "Name",
  "appList.createDialog.description": "Description",
  "appList.createDialog.ownerIds": "Owner user IDs",
  "appList.createDialog.developerIds": "Developer user IDs",
  "appList.createDialog.userIdsHint": "Separate multiple users with commas or new lines.",
  "appList.createDialog.failed": "Creation failed",

  "appList.generateAppKey": "Generate",

  "webhook.heading": "Webhook Delivery",

  "webhook.description": "EasyAuth pushes approval result callbacks, handover and onboarding events to the URLs below as signed POST requests. Verify the signature with the signing secret before processing an event. An empty URL receives no events.",

  "webhook.loadFailed": "Failed to load the webhook configuration",

  "webhook.saveFailed": "Failed to save the webhook configuration",

  "webhook.saveSuccess": "Webhook configuration saved",

  "webhook.notConfigured": "No webhook is configured for this application yet. The first save generates a signing secret shown only once — store it safely.",

  "webhook.enabled": "Enable webhook delivery",

  "webhook.field.approvalCallbackUrl": "Approval callback URL (approval_callback_url)",
  "webhook.field.handoverUrl": "Handover event URL (handover_url)",
  "webhook.field.onboardUrl": "Onboarding event URL (onboard_url)",

  "webhook.secretLabel": "Signing secret",

  "webhook.secretConfigured": "Configured",

  "webhook.secretMissing": "Not configured",

  "webhook.rotate": "Generate/rotate secret",

  "webhook.rotateTitle": "Rotate signing secret",

  "webhook.rotateMessage": "Old signatures become invalid immediately after rotation. Make sure the application side is ready to update the secret. Continue?",

  "webhook.rotateConfirm": "Confirm rotation",

  "webhook.secretTitle": "Webhook signing secret (shown only once)",

  "webhook.sendTest": "Send test event",

  "webhook.testFailed": "Failed to send the test event",

  "webhook.testResult": "Test event enqueued: delivery_id {deliveryId} (status {status})",

  "webhook.updatedMeta": "Last updated by {user} at {time}",

  "people.description": "Review everyone's employment status and start offboarding or transfer handovers.",

  "people.loadFailed": "Failed to load people",

  "people.status.active": "Active",
  "people.status.disabled": "Disabled",
  "people.status.departed": "Departed",

  "people.searchPlaceholder": "Search name / email / user ID",

  "people.column.name": "Name",
  "people.column.department": "Department",
  "people.column.email": "Email",
  "people.column.consoleAdmin": "Admin",

  "people.consoleAdmin.yes": "Yes",

  "people.empty.title": "No people",
  "people.empty.description": "No people match the current filters.",

  "people.goHandover": "Open handover",

  "people.startOffboard": "Start offboarding",

  "people.startTransfer": "Start transfer",

  "people.startDialog.offboardTitle": "Start offboarding handover",
  "people.startDialog.transferTitle": "Start transfer handover",
  "people.startDialog.offboardMessage": "An offboarding handover task will be created for \"{name}\". Their data stays untouched until the handover completes, and you can continue at any time.",
  "people.startDialog.transferMessage": "A transfer handover task will be created for \"{name}\". You can reassign data ownership, adjust their own access and teams in the task.",
  "people.startDialog.reason": "Reason",
  "people.startDialog.reasonHint": "Optional; recorded on the handover task.",
  "people.startDialog.confirm": "Create handover task",

  "people.startFailed": "Failed to create handover task",

  "people.permissions": "Permissions",

  "people.permissionsDialog.title": "Configure permissions",
  "people.permissionsDialog.message":
    "Configure permissions for \"{name}\". Only the administrator role is configurable here; other grants are managed in the application permission matrix.",
  "people.permissionsDialog.consoleAdmin": "Administrator",
  "people.permissionsDialog.consoleAdminCheckbox": "Make this person an administrator with console access",
  "people.permissionsDialog.consoleAdminHint":
    "When checked, the person sees the \"Console\" entry in the portal's top-right corner and can manage applications, permissions and people. Unchecking removes that entry.",
  "people.permissionsDialog.failed": "Failed to save permissions",
};
