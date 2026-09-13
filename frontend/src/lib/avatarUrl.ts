/**
 * 头像 URL 安全校验, 与后端 `accounts/avatar_url.py` 同一口径。
 *
 * 只接受 https 绝对地址或同源相对路径(`/…`, 非 `//`, 不含反斜杠)。
 * 空串、data:、http:、javascript:、协议相对地址一律视为缺失。
 * Authentik 无钉钉照片时会把 `data:image/svg+xml` 首字母图放进 OIDC `picture`,
 * EasyAuth 必须把它当成没有头像, 改走界面自己的首字母。
 */

export function safeAvatarUrl(value: string | null | undefined): string {
  const normalized = value?.trim() ?? "";
  if (!normalized) {
    return "";
  }
  if (normalized.includes("\\")) {
    return "";
  }
  if (normalized.startsWith("/") && !normalized.startsWith("//")) {
    return normalized;
  }
  try {
    const parsed = new URL(normalized);
    return parsed.protocol === "https:" && parsed.hostname !== "" ? normalized : "";
  } catch {
    return "";
  }
}
