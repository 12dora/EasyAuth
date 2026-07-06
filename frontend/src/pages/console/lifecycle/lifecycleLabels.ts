import type { MessageKey } from "../../../i18n/messages";
import type { JsonObject } from "../../../lib/api";
import type { HandoverAppActionRow } from "../../../lib/domain";
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
};

export function handoverKindLabel(t: Translator, kind: string): string {
  const key = KIND_KEYS[kind];
  return key ? t(key) : kind || "-";
}

const ACTION_STATUS_KEYS: Record<string, MessageKey> = {
  pending: "handover.actionStatus.pending",
  previewed: "handover.actionStatus.previewed",
  executing: "handover.actionStatus.executing",
  done: "handover.actionStatus.done",
  failed: "handover.actionStatus.failed",
  skipped: "handover.actionStatus.skipped",
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
      return "signal";
    case "executing":
      return "amber";
    case "previewed":
      return "bond";
    case "skipped":
      return "faint";
    default:
      // pending 是常态而非异常, 用中性色, 不做告警。
      return "neutral";
  }
}

export function actionReleasesToPool(action: HandoverAppActionRow): boolean {
  return action.policy?.unowned_strategy === "release_to_pool";
}

/** 应用交接卡的一句人话描述(不含技术细节)。 */
export function handoverActionSummary(t: Translator, action: HandoverAppActionRow): string {
  const receiverName = action.to_user?.name || action.to_user?.user_id || "";
  switch (action.status) {
    case "done":
      if (receiverName) {
        return t("handover.card.doneTo", { name: receiverName });
      }
      return actionReleasesToPool(action) ? t("handover.card.doneReleased") : t("handover.card.done");
    case "failed":
      return t("handover.card.failed");
    case "executing":
      return t("handover.card.executing");
    case "skipped":
      return t("handover.card.skipped");
    case "previewed":
      return receiverName ? t("handover.card.previewedTo", { name: receiverName }) : t("handover.card.previewed");
    default:
      if (receiverName) {
        return t("handover.card.pendingTo", { name: receiverName });
      }
      return actionReleasesToPool(action) ? t("handover.card.pendingRelease") : t("handover.card.waiting");
  }
}

export interface HandoverPreviewAsset {
  type: string;
  count: number;
  label: string;
}

/** 从 preview 响应(原样 JsonObject)中安全提取 assets 列表。 */
export function previewAssets(payload: JsonObject | null | undefined): HandoverPreviewAsset[] {
  const rawAssets = payload?.assets;
  if (!Array.isArray(rawAssets)) {
    return [];
  }
  const assets: HandoverPreviewAsset[] = [];
  for (const entry of rawAssets) {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      continue;
    }
    assets.push({
      type: typeof entry.type === "string" ? entry.type : "",
      count: typeof entry.count === "number" ? entry.count : 0,
      label: typeof entry.label === "string" ? entry.label : "",
    });
  }
  return assets;
}

export function previewHookSkipped(payload: JsonObject | null | undefined): boolean {
  return payload?.hook === "skipped";
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
