import type { MessageKey } from "../i18n/messages";

export type BadgeTone = "neutral" | "faint" | "ink" | "amber" | "evergreen" | "signal" | "bond";

/** 与 useI18n().t 对齐的翻译函数类型，供纯函数 helper 注入。 */
export type Translator = (key: MessageKey, vars?: Record<string, string | number>) => string;

const REQUEST_STATUS_KEYS: Record<string, MessageKey> = {
  submitted: "status.request.submitted",
  approved: "status.request.approved",
  rejected: "status.request.rejected",
  grant_applied: "status.request.grantApplied",
  grant_failed: "status.request.grantFailed",
};

export function accessRequestStatusLabel(t: Translator, status: string | null | undefined): string {
  if (!status) {
    return t("status.request.unknown");
  }
  const key = REQUEST_STATUS_KEYS[status];
  return key ? t(key) : status;
}

export function badgeToneForAccessRequestStatus(status: string | null | undefined): BadgeTone {
  switch (status) {
    case "grant_applied":
      return "evergreen";
    case "approved":
      return "bond";
    case "submitted":
      return "amber";
    case "rejected":
    case "grant_failed":
      return "signal";
    default:
      return "neutral";
  }
}

export function readinessLabel(t: Translator, status: string | null | undefined): string {
  switch (status) {
    case "ready":
      return t("status.readiness.ready");
    case "warning":
      return t("status.readiness.warning");
    // 后端配置检查的实际取值是 blocking(configuration.py); blocked 为历史兼容。
    case "blocking":
    case "blocked":
      return t("status.readiness.blocked");
    default:
      return status ?? t("status.readiness.unknown");
  }
}

export function readinessTone(status: string | null | undefined): BadgeTone {
  switch (status) {
    case "ready":
      return "evergreen";
    case "warning":
      return "amber";
    case "blocking":
    case "blocked":
      return "signal";
    default:
      return "neutral";
  }
}

// 依赖健康状态(health_models.py: healthy/warning/unhealthy/unknown)。
const HEALTH_STATUS_KEYS: Record<string, MessageKey> = {
  healthy: "ops.health.healthy",
  warning: "ops.health.warning",
  unhealthy: "ops.health.unhealthy",
  unknown: "ops.health.unknown",
};

export function healthStatusLabel(t: Translator, status: string | null | undefined): string {
  if (!status) {
    return t("ops.health.unknown");
  }
  const key = HEALTH_STATUS_KEYS[status];
  return key ? t(key) : status;
}

// 授权状态(grants/models.py: active/revoked/expired)。
const GRANT_STATUS_KEYS: Record<string, MessageKey> = {
  active: "ops.grantStatus.active",
  revoked: "ops.grantStatus.revoked",
  expired: "ops.grantStatus.expired",
};

export function grantStatusLabel(t: Translator, status: string | null | undefined): string {
  if (!status) {
    return "-";
  }
  const key = GRANT_STATUS_KEYS[status];
  return key ? t(key) : status;
}

// 审批实例状态(与 ApprovalInstancesPage 的筛选项共用一套 key)。
export const APPROVAL_STATUS_LABEL_KEYS: Record<string, MessageKey> = {
  created: "approvalInstances.status.created",
  submitted: "approvalInstances.status.submitted",
  approved: "approvalInstances.status.approved",
  rejected: "approvalInstances.status.rejected",
  canceled: "approvalInstances.status.canceled",
  failed: "approvalInstances.status.failed",
};

export function approvalStatusLabel(t: Translator, status: string | null | undefined): string {
  if (!status) {
    return "-";
  }
  const key = APPROVAL_STATUS_LABEL_KEYS[status];
  return key ? t(key) : status;
}

// webhook 投递状态(与审批实例投递列共用一套 key)。
const DELIVERY_STATE_KEYS: Record<string, MessageKey> = {
  pending: "approvalInstances.delivery.pending",
  delivered: "approvalInstances.delivery.delivered",
  failed: "approvalInstances.delivery.failed",
  skipped: "approvalInstances.delivery.skipped",
};

export function deliveryStateLabel(t: Translator, state: string | null | undefined): string {
  if (!state) {
    return "-";
  }
  const key = DELIVERY_STATE_KEYS[state];
  return key ? t(key) : state;
}

export function grantTypeLabel(t: Translator, grantType: string | null | undefined): string {
  switch (grantType) {
    case "permanent":
      return t("status.grantType.permanent");
    case "timed":
      return t("status.grantType.timed");
    default:
      return grantType ?? "-";
  }
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
