/**
 * 门户与控制台各自注册路由与 guard；共享组件通过 surface adapter 注入路径，
 * 禁止字符串替换 URL 前缀（01 §6.3）。
 */
export type HandoverSurface = "portal" | "console";

export function handoverTaskPath(surface: HandoverSurface, taskId: number | string): string {
  return surface === "portal"
    ? `/portal/api/v1/handover-tasks/${taskId}`
    : `/console/api/v1/lifecycle/handover-tasks/${taskId}`;
}

export function handoverActionPath(
  surface: HandoverSurface,
  taskId: number | string,
  appKey: string,
  suffix = "",
): string {
  const base = `${handoverTaskPath(surface, taskId)}/actions/${encodeURIComponent(appKey)}`;
  return suffix ? `${base}/${suffix}` : base;
}

export function handoverAssetTypePath(
  surface: HandoverSurface,
  taskId: number | string,
  appKey: string,
  assetType: string,
): string {
  return `${handoverActionPath(surface, taskId, appKey)}/assets/${encodeURIComponent(assetType)}`;
}

export function handoverCandidatesUrl(
  surface: HandoverSurface,
  taskId: number | string,
  query: string,
): string {
  if (surface === "portal") {
    return `/portal/api/v1/handover-candidates?purpose=receiver&q=${encodeURIComponent(query)}`;
  }
  return `${handoverTaskPath("console", taskId)}/candidates?q=${encodeURIComponent(query)}`;
}

export function daysLeftTone(daysLeft: number | null | undefined): "neutral" | "amber" | "signal" {
  if (daysLeft === null || daysLeft === undefined) {
    return "neutral";
  }
  if (daysLeft < 3) {
    return "signal";
  }
  if (daysLeft <= 7) {
    return "amber";
  }
  return "neutral";
}
