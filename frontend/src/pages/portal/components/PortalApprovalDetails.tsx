import type { ReactNode } from "react";

import { StatusBanner } from "../../../components/StatusBanner";
import type { Translator } from "../../../lib/status";
import { formatDateTime, grantTypeLabel } from "../../../lib/status";

import {
  approvalFactsAreComplete,
  decisionAlreadyCommitted,
  grantLabel,
  requestTypeLabel,
} from "./portalApprovalFacts";
import type { ApprovalAuthorizationGroup, ApprovalGrantFact, PortalApprovalRow } from "./portalApprovalTypes";

/** 列表与弹窗共用的申请内容摘要: 申请类型 + 授权组事实 + 直接授权事实。 */
export function approvalContentDetails(t: Translator, approval: PortalApprovalRow): ReactNode {
  const hasTargets = approval.authorization_groups.length > 0 || approval.direct_grants.length > 0;
  return (
    <div className="grid min-w-64 gap-2 text-xs leading-5">
      <strong className="text-ink">{requestTypeLabel(t, approval.request_type)}</strong>
      {approval.authorization_groups.map((group) => (
        <div key={`${group.kind}:${group.key}`}>{authorizationGroupFacts(t, group)}</div>
      ))}
      {approval.direct_grants.length > 0 ? (
        <div>
          <span className="font-semibold text-ink-soft">{t("portal.column.directGrants")}</span>
          {grantList(approval.direct_grants)}
        </div>
      ) : null}
      {!hasTargets && approval.request_type === "revoke" ? (
        <span className="text-ink-soft">{t("portal.approvals.fullRevoke")}</span>
      ) : null}
    </div>
  );
}

function authorizationGroupFacts(t: Translator, group: ApprovalAuthorizationGroup): ReactNode {
  return (
    <>
      <span className="font-semibold text-ink-soft">
        {t("portal.column.groups")}: {group.name || group.key} [{group.kind}]
      </span>
      {group.grants.length > 0 ? (
        grantList(group.grants)
      ) : (
        <StatusBanner tone="signal" title={t("portal.approvals.groupWithoutGrants")} />
      )}
    </>
  );
}

function grantList(grants: ApprovalGrantFact[]): ReactNode {
  return (
    <ul className="mt-0.5 grid gap-0.5 pl-3 text-ink-faint">
      {grants.map((grant) => (
        <li key={`${grant.permission}:${grant.scope}`}>{grantLabel(grant)}</li>
      ))}
    </ul>
  );
}

/** 决定弹窗里的完整事实块: 未加载完成前只给状态条, 不给可提交的事实。 */
export function decisionDetails(
  t: Translator,
  approval: PortalApprovalRow | undefined,
  isLoading: boolean,
  error: Error | null,
): ReactNode {
  if (isLoading) {
    return <StatusBanner title={t("common.loading")} />;
  }
  if (error || !approval) {
    return (
      <StatusBanner
        live="alert"
        tone="signal"
        title={t("portal.approvals.detailLoadFailed")}
        message={error?.message}
      />
    );
  }
  return (
    <section className="grid gap-3 rounded-[3px] border border-ink/12 bg-paper-deep/20 p-3">
      <strong className="text-sm text-ink">{t("portal.approvals.facts")}</strong>
      {approvalContentDetails(t, approval)}
      {decisionFactFields(t, approval)}
      {decisionWarningBanner(t, approval)}
    </section>
  );
}

function decisionFactFields(t: Translator, approval: PortalApprovalRow): ReactNode {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs leading-5">
      <dt className="text-ink-faint">{t("portal.column.term")}</dt>
      <dd>{grantTypeLabel(t, approval.grant_type)}</dd>
      {approval.grant_expires_at ? (
        <>
          <dt className="text-ink-faint">{t("portal.column.expiresAt")}</dt>
          <dd>{formatDateTime(approval.grant_expires_at)}</dd>
        </>
      ) : null}
      <dt className="text-ink-faint">{t("portal.column.reason")}</dt>
      <dd>{approval.reason || "-"}</dd>
      {approval.request_type !== "grant" ? (
        <>
          <dt className="text-ink-faint">{t("portal.approvals.baseRevision")}</dt>
          <dd>
            {approval.base_grant_id}.{approval.base_grant_revision}
          </dd>
        </>
      ) : null}
    </dl>
  );
}

function decisionWarningBanner(t: Translator, approval: PortalApprovalRow): ReactNode {
  if (decisionAlreadyCommitted(approval)) {
    return <StatusBanner tone="amber" title={t("approvals.conflict")} />;
  }
  if (!approvalFactsAreComplete(approval)) {
    return <StatusBanner tone="signal" title={t("portal.approvals.groupWithoutGrants")} />;
  }
  return null;
}
