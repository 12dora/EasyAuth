import type { ApprovalDecisionMode } from "../../../components/ApprovalDecisionDialog";
import type { Pagination } from "../../../lib/api";
import type { PortalApprovalApplicant } from "../../../lib/domain";

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
  kind: string;
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
  decided_at: string | null;
  decision_comment: string | null;
  applicant: Required<PortalApprovalApplicant>;
  approver_user_ids: string[];
  decided_by: string | null;
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
