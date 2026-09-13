import type { GrantPermissionsRow } from "../../../components/grants/GrantPermissionsCell";
import { userOptionName } from "../../../components/UserCombobox";
import type { Translator } from "../../../lib/status";

import type { ApprovalGrantFact, ApprovalNoticeKey, PortalApprovalRow } from "./portalApprovalTypes";

/** 需要读屏立刻播报的提示: 冲突/需重提/授权未落地三类都属于告警。 */
const ALERT_NOTICE_KEYS: readonly ApprovalNoticeKey[] = [
  "approvals.conflict",
  "approvals.resubmitRequired",
  "approvals.grantFailedCommitted",
  "status.request.grantExpired",
];

export function applicantLabel(approval: PortalApprovalRow): string {
  return userOptionName(approval.applicant) || "-";
}

export function grantLabel(grant: ApprovalGrantFact): string {
  const name = grant.permission_name || grant.permission;
  return `${name} (${grant.permission}) · ${grant.scope}`;
}

/** 把审批行的授权组 + 直接授权压成「我的权限 → 权限详情」单元格同一份形状。 */
export function approvalPermissionsRow(approval: PortalApprovalRow): GrantPermissionsRow {
  return {
    groups: approval.authorization_groups.map((group) => ({ key: group.key, name: group.name })),
    grants: [
      ...approval.authorization_groups.flatMap((group) =>
        group.grants.map((grant) => ({
          source_type: "group",
          source_key: group.key,
          permission_name: grant.permission_name || grant.permission,
          scope_name: grant.scope,
        })),
      ),
      ...approval.direct_grants.map((grant) => ({
        source_type: "direct",
        source_key: null,
        permission_name: grant.permission_name || grant.permission,
        scope_name: grant.scope,
      })),
    ],
  };
}

export function requestTypeLabel(t: Translator, requestType: string): string {
  switch (requestType) {
    case "grant":
      return t("portal.approvals.requestType.grant");
    case "change":
      return t("portal.approvals.requestType.change");
    case "revoke":
      return t("portal.approvals.requestType.revoke");
    case "renew":
      return t("portal.approvals.requestType.renew");
    default:
      return requestType;
  }
}

export function approvalFactsAreComplete(approval: PortalApprovalRow): boolean {
  if (approval.authorization_groups.some((group) => group.grants.length === 0)) {
    return false;
  }
  if (approval.grant_type === "timed" && !approval.grant_expires_at) {
    return false;
  }
  const targetCount =
    approval.direct_grants.length +
    approval.authorization_groups.reduce((count, group) => count + group.grants.length, 0);
  return approval.reason.trim().length > 0 && (approval.request_type === "revoke" || targetCount > 0);
}

export function approvalIsDecidable(approval: PortalApprovalRow, expectedId: number): boolean {
  return (
    approval.id === expectedId &&
    approval.status === "submitted" &&
    approval.decided_at === null &&
    !approval.decided_by &&
    approvalFactsAreComplete(approval)
  );
}

/** 决定已提交(状态已变更/已有决定人或决定时间)时不得再次提交。 */
export function decisionAlreadyCommitted(approval: PortalApprovalRow): boolean {
  return approval.status !== "submitted" || approval.decided_at !== null || Boolean(approval.decided_by);
}

export function noticeLive(noticeKey: ApprovalNoticeKey): "alert" | "status" {
  return ALERT_NOTICE_KEYS.includes(noticeKey) ? "alert" : "status";
}

export function noticeTone(noticeKey: ApprovalNoticeKey): "amber" | "signal" | "evergreen" {
  if (noticeKey === "approvals.conflict") {
    return "amber";
  }
  return ALERT_NOTICE_KEYS.includes(noticeKey) ? "signal" : "evergreen";
}
