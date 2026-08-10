import type { MessageKey } from "../../../i18n/messages";
import type { HandoverAction } from "../../../lib/domain";
import type { BadgeTone, Translator } from "../../../lib/status";

const PERSON_STATUS_KEYS: Record<string, MessageKey> = {
  active: "people.status.active",
  disabled: "people.status.disabled",
  departed: "people.status.departed",
};

export function personStatusLabel(t: Translator, status: string): string {
  const key = PERSON_STATUS_KEYS[status];
  return key ? t(key) : status || "-";
}

export function personStatusTone(status: string): BadgeTone {
  switch (status) {
    case "active":
      return "evergreen";
    case "disabled":
      return "neutral";
    case "departed":
      return "faint";
    default:
      return "neutral";
  }
}

const TASK_STATUS_KEYS: Record<string, MessageKey> = {
  pending: "handover.taskStatus.pending",
  in_progress: "handover.taskStatus.inProgress",
  completed: "handover.taskStatus.completed",
  cancelled: "handover.taskStatus.cancelled",
};

export function handoverTaskStatusLabel(t: Translator, status: string): string {
  const key = TASK_STATUS_KEYS[status];
  return key ? t(key) : status || "-";
}

export function handoverTaskStatusTone(status: string): BadgeTone {
  switch (status) {
    case "pending":
      return "amber";
    case "in_progress":
      return "bond";
    case "completed":
      return "evergreen";
    case "cancelled":
      return "faint";
    default:
      return "neutral";
  }
}

const KIND_KEYS: Record<string, MessageKey> = {
  offboard: "handover.kind.offboard",
  transfer: "handover.kind.transfer",
  pre_offboard: "handover.kind.pre_offboard",
  reassign: "handover.kind.reassign",
};

export function handoverKindLabel(t: Translator, kind: string): string {
  const key = KIND_KEYS[kind];
  return key ? t(key) : kind || "-";
}

const ACTION_STATUS_KEYS: Record<string, MessageKey> = {
  pending: "handover.actionStatus.pending",
  previewed: "handover.actionStatus.previewed",
  executing: "handover.actionStatus.executing",
  async_pending: "handover.actionStatus.asyncPending",
  done: "handover.actionStatus.done",
  failed: "handover.actionStatus.failed",
  skipped: "handover.actionStatus.skipped",
  blocked: "handover.actionStatus.blocked",
  async_attention_required: "handover.actionStatus.asyncAttentionRequired",
};

export function handoverActionStatusLabel(t: Translator, status: string): string {
  const key = ACTION_STATUS_KEYS[status];
  return key ? t(key) : status || "-";
}

export function handoverActionStatusTone(status: string): BadgeTone {
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

const ASSIGNEE_STATE_KEYS: Record<string, MessageKey> = {
  manager: "handover.assigneeState.manager",
  subject: "handover.assigneeState.subject",
  superuser_pool: "handover.assigneeState.superuser_pool",
};

export function handoverAssigneeStateLabel(t: Translator, state: string): string {
  const key = ASSIGNEE_STATE_KEYS[state];
  return key ? t(key) : state || "-";
}

/** 应用交接卡的一句人话描述。 */
export function handoverActionSummary(t: Translator, action: HandoverAction): string {
  const grantName = action.grant_receiver?.name || action.grant_receiver?.user_id || "";
  switch (action.status) {
    case "done":
      return grantName ? t("handover.card.doneTo", { name: grantName }) : t("handover.card.done");
    case "failed":
      return t("handover.card.failed");
    case "executing":
      return t("handover.card.executing");
    case "async_pending":
      return t("handover.card.asyncPending");
    case "skipped":
      return t("handover.card.skipped");
    case "blocked":
      return t("handover.actionStatus.blocked");
    case "async_attention_required":
      return t("handover.actionStatus.asyncAttentionRequired");
    case "previewed":
      return t("handover.card.previewed");
    default:
      return t("handover.card.waiting");
  }
}

export interface ParsedGrantKey {
  appKey: string;
  kind: string;
  key: string;
  scopeKey: string;
}

/** 拆解转岗差异 key: "app:group:sales" / "app:permission:customer.view:GLOBAL"。 */
export function parseGrantDiffKey(raw: string): ParsedGrantKey {
  const [appKey = "", kind = "", key = "", scopeKey = ""] = raw.split(":");
  return { appKey, kind, key, scopeKey };
}
