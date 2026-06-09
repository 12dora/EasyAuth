export type BadgeTone = "neutral" | "primary" | "success" | "warning" | "danger";

const REQUEST_STATUS_LABELS: Record<string, string> = {
  submitted: "已提交",
  approved: "已批准",
  rejected: "已拒绝",
  grant_applied: "已授权",
  grant_failed: "授权失败",
};

export function accessRequestStatusLabel(status: string | null | undefined): string {
  if (!status) {
    return "未知";
  }
  return REQUEST_STATUS_LABELS[status] ?? status;
}

export function badgeToneForAccessRequestStatus(status: string | null | undefined): BadgeTone {
  switch (status) {
    case "grant_applied":
      return "success";
    case "approved":
      return "primary";
    case "submitted":
      return "warning";
    case "rejected":
    case "grant_failed":
      return "danger";
    default:
      return "neutral";
  }
}

export function readinessLabel(status: string | null | undefined): string {
  switch (status) {
    case "ready":
      return "就绪";
    case "warning":
      return "需关注";
    case "blocked":
      return "阻塞";
    default:
      return status ?? "未知";
  }
}

export function readinessTone(status: string | null | undefined): BadgeTone {
  switch (status) {
    case "ready":
      return "success";
    case "warning":
      return "warning";
    case "blocked":
      return "danger";
    default:
      return "neutral";
  }
}

export function grantTypeLabel(grantType: string | null | undefined): string {
  switch (grantType) {
    case "permanent":
      return "长期";
    case "timed":
      return "限时";
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
