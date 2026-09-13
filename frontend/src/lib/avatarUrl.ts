/**
 * 头像 URL 安全校验, 与后端 `accounts/avatar_url.py` 同一口径。
 *
 * 只接受 https 绝对地址、同源相对路径(`/…`, 非 `//`, 不含反斜杠),
 * 以及白名单内联图: 精确小写前缀
 * `data:image/svg+xml;base64,` / `data:image/png;base64,` /
 * `data:image/jpeg;base64,` / `data:image/webp;base64,`,
 * 体仅为 `[A-Za-z0-9+/=]`, 总长不超过 16384。
 * 空串、其它 data:、http:、javascript:、协议相对地址一律视为缺失。
 * Authentik 无钉钉照片时会把 `data:image/svg+xml;base64,...` 首字母图放进 OIDC `picture`,
 * EasyAuth 按照片渲染。
 */

const INLINE_IMAGE_PREFIXES = [
  "data:image/svg+xml;base64,",
  "data:image/png;base64,",
  "data:image/jpeg;base64,",
  "data:image/webp;base64,",
] as const;

const INLINE_IMAGE_BODY = /^[A-Za-z0-9+/=]+$/;
const INLINE_IMAGE_MAX_LENGTH = 16384;

function isSafeInlineImageUrl(value: string): boolean {
  if (value.length > INLINE_IMAGE_MAX_LENGTH) {
    return false;
  }
  const prefix = INLINE_IMAGE_PREFIXES.find((item) => value.startsWith(item));
  if (prefix === undefined) {
    return false;
  }
  return INLINE_IMAGE_BODY.test(value.slice(prefix.length));
}

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
  if (normalized.startsWith("data:")) {
    return isSafeInlineImageUrl(normalized) ? normalized : "";
  }
  try {
    const parsed = new URL(normalized);
    return parsed.protocol === "https:" && parsed.hostname !== "" ? normalized : "";
  } catch {
    return "";
  }
}
