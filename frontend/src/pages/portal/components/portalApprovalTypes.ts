import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import type { Pagination } from "../../../lib/api";
import type {
  AuthorizationGroupKind,
  PortalApprovalApplicant,
  PortalRequestApprover,
} from "../../../lib/domain";

export type ApprovalTab = "pending" | "processed";
export const APPROVAL_TAB_KEYS = ["pending", "processed"] as const satisfies readonly ApprovalTab[];

export type ApprovalNoticeKey =
  | "approvals.approved"
  | "approvals.rejected"
  | "approvals.conflict"
  | "approvals.resubmitRequired"
  | "approvals.grantFailedCommitted"
  | "status.request.grantExpired"
  | "";

export type CommittedGrantStatus = "grant_failed" | "grant_expired";

export interface ApprovalGrantFact {
  permission: string;
  permission_name: string;
  scope: string;
}

export interface ApprovalAuthorizationGroup {
  key: string;
  kind: AuthorizationGroupKind;
  name: string;
  grants: ApprovalGrantFact[];
}

export interface PortalApprovalRow {
  id: number;
  app_key: string;
  app_name: string;
  request_type: string;
  base_grant_id: number | null;
  base_grant_revision: number | null;
  status: string;
  status_label: string;
  grant_type: string;
  grant_expires_at: string | null;
  reason: string;
  submitted_at: string;
  authorization_groups: ApprovalAuthorizationGroup[];
  direct_grants: ApprovalGrantFact[];
  /** 仅 status 为 submitted 时非空: 当前待处理的审批人分配。 */
  current_approvers: PortalRequestApprover[];
  decided_at: string | null;
  decision_comment: string | null;
  applicant: Required<PortalApprovalApplicant>;
  approver_user_ids: string[];
  decided_by: string | null;
  /** 决定人身份: user / console_admin; 未决时为空字符串。 */
  decision_actor_type: string;
  /** 决定人显示名; 后端解析不出姓名时为 null(此时只能回退展示 decided_by)。 */
  decided_by_name: string | null;
}

export interface ApprovalListPayload {
  data: PortalApprovalRow[];
  pagination: Pagination;
}

export interface PendingDecision {
  mode: ApprovalDecisionMode;
  approval: PortalApprovalRow;
}

/** 审批详情查询的呈现态: 加载中/失败/已到手事实, 决定弹窗据此决定能否提交。 */
export interface ApprovalDetailState {
  approval: PortalApprovalRow | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: Error | null;
}

export const DEFAULT_PAGE_SIZE = 20;
