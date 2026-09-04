import { Modal, Steps, type StepsProps } from "antd";
import type { ReactNode } from "react";

import { useI18n } from "../../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import { GrantExpiryCell } from "../grantExpiry";
import { formatGrantGroupNames } from "../grantGroupNames";
import type { PortalRequestRow } from "../portalListPayload";

type FlowStep = NonNullable<StepsProps["items"]>[number];

/** 单条申请的时间格式化器: 弹窗内多处复用同一份 locale。 */
type DateTimeFormatter = (value: string | null | undefined) => string;

/**
 * 申请详情弹窗。
 *
 * 上半部是申请内容摘要(表格里放不下的直接授权在这里展开), 下半部是审批流程图 ——
 * 员工问的从来不是「状态字段等于什么」, 而是「走到哪一步了、卡在谁那里、什么时候到期」,
 * 所以四个时刻(提交 / 审批 / 生效 / 到期)按流程排成一条线, 而不是列成一堆字段。
 */
export function PortalRequestDetailDialog({ row, onClose }: { row: PortalRequestRow; onClose: () => void }) {
  const { formatDateTime, t } = useI18n();

  return (
    <Modal open title={t("portal.requests.detailTitle")} footer={null} width={720} onCancel={onClose}>
      <div className="grid gap-5 pt-2">
        <section className="grid gap-2">
          <strong className="text-sm text-ink">{t("portal.requests.detailSummary")}</strong>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-body leading-5">
            <dt className="text-ink-faint">{t("common.app")}</dt>
            <dd>{formatAppDisplayName({ name: row.app_name, alias: row.app_alias })}</dd>
            <dt className="text-ink-faint">{t("portal.column.groups")}</dt>
            <dd>{formatGrantGroupNames(row.authorization_groups)}</dd>
            <dt className="text-ink-faint">{t("portal.column.directGrants")}</dt>
            <dd>{directGrantList(row)}</dd>
            <dt className="text-ink-faint">{t("portal.column.expiresAt")}</dt>
            <dd>
              <GrantExpiryCell grantType={row.grant_type} expiresAt={row.grant_expires_at} />
            </dd>
            <dt className="text-ink-faint">{t("portal.column.reason")}</dt>
            <dd className="whitespace-pre-wrap">{row.reason || "-"}</dd>
          </dl>
        </section>
        <section className="grid gap-3">
          <strong className="text-sm text-ink">{t("portal.requests.flow.title")}</strong>
          <Steps items={flowSteps(row, t, formatDateTime)} labelPlacement="vertical" size="small" />
        </section>
      </div>
    </Modal>
  );
}

/** 直接授权用「权限名 · 范围」列出; 只申请了权限组的申请这里是 "-"。 */
function directGrantList(row: PortalRequestRow): ReactNode {
  if (row.direct_grants.length === 0) {
    return "-";
  }
  return (
    <ul className="grid gap-0.5">
      {row.direct_grants.map((grant) => (
        <li key={`${grant.permission}:${grant.scope}`}>
          {grant.permission_name} · {grant.scope}
        </li>
      ))}
    </ul>
  );
}

/**
 * 审批流程的节点: 提交申请 -> 审批(撤回的申请换成「已撤回」) -> 权限生效 -> 到期。
 * 「到期」只有限时授权才有, 长期授权画一个永远走不到的节点只会让人以为权限会被收走。
 */
function flowSteps(row: PortalRequestRow, t: ReturnType<typeof useI18n>["t"], formatDateTime: DateTimeFormatter): FlowStep[] {
  const steps: FlowStep[] = [
    {
      title: t("portal.requests.flow.submitted"),
      description: formatDateTime(row.submitted_at),
      status: "finish",
    },
    approvalStep(row, t, formatDateTime),
    effectiveStep(row, t, formatDateTime),
  ];
  // grant_expired 表示审批通过后授权窗口已过、从未生效, 生效节点已经以错误态说明了原因, 不再挂一个到期节点。
  if (row.grant_expires_at && row.status !== "grant_expired") {
    steps.push({
      title: t("portal.requests.flow.expiry"),
      description: formatDateTime(row.grant_expires_at),
      status: "wait",
    });
  }
  return steps;
}

function approvalStep(row: PortalRequestRow, t: ReturnType<typeof useI18n>["t"], formatDateTime: DateTimeFormatter): FlowStep {
  if (row.status === "withdrawn") {
    // 申请人自己撤回时流程并没有走到审批, 因此这个节点整个换成「已撤回」。
    return {
      title: t("portal.requests.flow.withdrawn"),
      description: formatDateTime(row.withdrawn_at),
      status: "finish",
    };
  }
  const title = t("portal.requests.flow.approval");
  if (row.status === "submitted") {
    return {
      title,
      description: row.current_approvers.map((approver) => approver.name).join(t("portal.requests.approverSeparator")) || "-",
      status: "process",
    };
  }
  return {
    title,
    description: (
      <span className="grid gap-0.5">
        <span>{row.decided_by_name ?? row.decided_by}</span>
        <span className="tabular">{formatDateTime(row.decided_at)}</span>
        {row.decision_comment ? (
          <span>
            {t("approvals.comment")}：{row.decision_comment}
          </span>
        ) : null}
      </span>
    ),
    status: row.status === "rejected" ? "error" : "finish",
  };
}

function effectiveStep(row: PortalRequestRow, t: ReturnType<typeof useI18n>["t"], formatDateTime: DateTimeFormatter): FlowStep {
  const title = t("portal.requests.flow.applied");
  // grant_expired 与失败/冲突同类: 后端语义是「授权期限已过, 未应用」, applied_at 恒为空。
  if (row.status === "grant_failed" || row.status === "grant_conflict" || row.status === "grant_expired") {
    return { title, description: row.status_label, status: "error" };
  }
  if (row.applied_at) {
    return { title, description: formatDateTime(row.applied_at), status: "finish" };
  }
  return { title, status: "wait" };
}
