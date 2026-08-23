import { apiErrorReason } from "../../lib/apiErrorReason";
import type { HandoverAction } from "../../lib/domain";
import type { BadgeTone, Translator } from "../../lib/status";
import { buildExecuteConfirmParts } from "./assetAllocatorModel";

export type DateTimeFormatter = (value: string | null | undefined) => string;

/** 交接卡外框配色: 阻断/数据阶段失败最重, 授权阶段失败与人工介入次之。 */
export function actionPanelToneClass(action: HandoverAction): string {
  const status = action.status;
  if (status === "blocked" || (status === "failed" && !action.data_completed_at)) {
    return "border-signal/30 bg-signal/5";
  }
  if ((status === "failed" && action.data_completed_at) || status === "async_attention_required") {
    return "border-amber/30 bg-amber/5";
  }
  if (status === "skipped") {
    return "border-ink/10 bg-paper-deep/50";
  }
  if (status === "done") {
    return "border-evergreen/30 bg-evergreen/5";
  }
  return "border-ink/12 bg-paper-soft";
}

export type ActionErrorEffect =
  | { kind: "snapshot_stale" }
  | { kind: "confirm_version_stale" }
  | { kind: "downstream_locked" }
  // 413 payload_too_large：action 保持 previewed 并返回 batch_progress，刷新后出现 [执行下一批]
  | { kind: "payload_too_large" }
  | { kind: "message"; message: string };

export function classifyActionError(error: Error): ActionErrorEffect {
  const reason = apiErrorReason(error);
  if (reason === "snapshot_stale") {
    return { kind: "snapshot_stale" };
  }
  if (reason === "confirm_version_stale") {
    return { kind: "confirm_version_stale" };
  }
  if (reason === "downstream_locked") {
    return { kind: "downstream_locked" };
  }
  if (reason === "payload_too_large") {
    return { kind: "payload_too_large" };
  }
  return { kind: "message", message: error.message };
}

export function resolveConfirmReceiver(
  confirmParts: ReturnType<typeof buildExecuteConfirmParts>,
  action: HandoverAction,
  t: Translator,
): string {
  if (confirmParts.uniqueReceiverNames.length > 1) {
    return t("handover.portal.detail.multiReceivers", { count: confirmParts.uniqueReceiverNames.length });
  }
  if (confirmParts.uniqueReceiverNames.length === 1) {
    return confirmParts.uniqueReceiverNames[0];
  }
  return action.grant_receiver?.name || "-";
}

/** 跳过信息优先取 action 字段, 缺失时回落到最后一条 skip_history。 */
function latestSkipRecord(action: HandoverAction) {
  const latest = action.skip_history[action.skip_history.length - 1];
  return {
    latest,
    who: action.skipped_by || latest?.actor_id || "",
    when: action.skipped_at || latest?.skipped_at || null,
    reason: action.skip_reason || latest?.reason || "",
  };
}

export function resolveSkipDisplay(action: HandoverAction, t: Translator, fmt: DateTimeFormatter): string {
  const { latest, who, when, reason } = latestSkipRecord(action);
  if (!who && !when && action.skip_history.length === 0) {
    return t("handover.portal.detail.skipMissingActor");
  }
  if (!who && latest) {
    return t("handover.portal.detail.skippedBy", {
      who: latest.actor_id,
      when: fmt(latest.skipped_at),
      reason: latest.reason,
    });
  }
  if (!who) {
    return t("handover.portal.detail.skipMissingActor");
  }
  return t("handover.portal.detail.skippedBy", {
    who,
    when: when ? fmt(when) : "-",
    reason,
  });
}

export function actionStatusLabel(t: Translator, status: HandoverAction["status"]): string {
  switch (status) {
    case "pending":
      return t("handover.actionStatus.pending");
    case "previewed":
      return t("handover.actionStatus.previewed");
    case "executing":
      return t("handover.actionStatus.executing");
    case "async_pending":
      return t("handover.actionStatus.asyncPending");
    case "done":
      return t("handover.actionStatus.done");
    case "failed":
      return t("handover.actionStatus.failed");
    case "skipped":
      return t("handover.actionStatus.skipped");
    case "blocked":
      return t("handover.actionStatus.blocked");
    case "async_attention_required":
      return t("handover.actionStatus.asyncAttentionRequired");
    default:
      return status;
  }
}

export function actionStatusBadgeTone(status: HandoverAction["status"]): BadgeTone {
  switch (status) {
    case "done":
      return "evergreen";
    case "failed":
    case "blocked":
      return "signal";
    case "executing":
    case "async_pending":
    case "async_attention_required":
      return "amber";
    case "previewed":
      return "bond";
    case "skipped":
      return "faint";
    default:
      return "neutral";
  }
}
