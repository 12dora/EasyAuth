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
    case "blocked":
      return "signal";
    default:
      return "neutral";
  }
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
