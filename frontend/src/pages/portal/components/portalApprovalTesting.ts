import type { PortalApprovalRow } from "./portalApprovalTypes";

/**
 * 门户审批测试共用的行事实。
 *
 * 这里刻意逐字对齐后端 `/portal/api/v1/me/approvals` 的真实序列化字段
 * (`_access_request_item` + `_approval_item`, 共 26 个 key)。
 * `parseApprovalListPayload` 按 key 数量精确匹配, 所以夹具一旦少一个字段,
 * 用例就会在一份「后端根本不会返回的形状」上通过, 掩盖真实的契约漂移。
 *
 * 不加类型标注(只用 satisfies)是为了保留字面量推导出的索引签名,
 * 这样夹具还能直接传给按 `Record<string, unknown>` 收参的响应构造函数。
 */
export const pendingApproval = {
  id: 42,
  app_key: "crm",
  app_name: "CRM",
  app_alias: "客户管理",
  request_type: "grant",
  base_grant_id: null,
  base_grant_revision: null,
  status: "submitted",
  // status_label 由后端 status_text.status_label 下发, 这里用它的真实取值。
  status_label: "等待审批",
  grant_type: "permanent",
  grant_expires_at: null,
  reason: "处理跨部门工单",
  submitted_at: "2026-07-01T09:00:00Z",
  authorization_groups: [
    {
      key: "sales-reader",
      kind: "role",
      name: "销售只读",
      grants: [{ permission: "orders.list", permission_name: "订单列表", scope: "SELF" }],
    },
  ],
  direct_grants: [
    { permission: "orders.read", permission_name: "查看订单", scope: "SELF" },
    { permission: "orders.export", permission_name: "导出订单", scope: "SELF" },
  ],
  current_approvers: [{ user_id: "me", name: "我本人" }],
  decided_at: null,
  decision_comment: null,
  applicant: { user_id: "u-1", name: "张三", email: "zhangsan@example.test", department: "销售部" },
  approver_user_ids: ["me"],
  decided_by: "",
  decision_actor_type: "",
  decided_by_name: null,
  approved_at: null,
  applied_at: null,
  withdrawn_at: null,
} satisfies PortalApprovalRow;

const APPROVED_AT = "2026-07-02T09:00:00Z";
const APPLIED_AT = "2026-07-02T09:00:05Z";
const WITHDRAWN_AT = "2026-07-02T09:00:00Z";

/**
 * 生命周期时间戳的真实取值只由 status 决定, 这张表逐条抄自后端数据库约束
 * `access_requests_status_field_shape`。未知状态直接抛错, 不给静默默认值 ——
 * 否则夹具会造出一条后端永远不可能返回的行。
 */
function timelineForStatus(status: string): Pick<PortalApprovalRow, "approved_at" | "applied_at" | "withdrawn_at"> {
  switch (status) {
    case "submitted":
    case "rejected":
      return { approved_at: null, applied_at: null, withdrawn_at: null };
    case "approved":
    case "grant_failed":
    case "grant_conflict":
    case "grant_expired":
      return { approved_at: APPROVED_AT, applied_at: null, withdrawn_at: null };
    case "grant_applied":
      return { approved_at: APPROVED_AT, applied_at: APPLIED_AT, withdrawn_at: null };
    case "withdrawn":
      return { approved_at: null, applied_at: null, withdrawn_at: WITHDRAWN_AT };
    default:
      throw new Error(`未知的申请状态: ${status}`);
  }
}

/**
 * 已决行: 后端在申请离开 submitted 后会清空 `current_approvers`,
 * 并把决定人三件套填成真实取值。已处理页签与「决定已提交」类用例必须用这个形状,
 * 否则测的是一个待办行披着已决状态的假事实。
 */
export function decidedApproval(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...pendingApproval,
    current_approvers: [],
    decided_by: "me",
    decision_actor_type: "user",
    decided_by_name: "我本人",
    decided_at: "2026-07-02T09:00:00Z",
    // 时间戳按最终 status 取值, 保证覆盖 status 的用例拿到的仍是后端会真实返回的行。
    ...timelineForStatus(typeof overrides.status === "string" ? overrides.status : pendingApproval.status),
    ...overrides,
  };
}
