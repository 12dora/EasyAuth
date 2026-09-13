import { cn } from "../lib/cn";
import { safeAvatarUrl } from "../lib/avatarUrl";

export const PERSON_AVATAR_SIZES = [20, 24, 32] as const;

export type PersonAvatarSize = (typeof PERSON_AVATAR_SIZES)[number];

const SIZE_CLASS: Record<PersonAvatarSize, string> = {
  20: "h-5 w-5 text-[10px]",
  24: "h-6 w-6 text-[11px]",
  32: "h-8 w-8 text-xs",
};

/**
 * 人员头像: 安全 URL 才渲染照片, 否则用姓名首字母。
 * 中日韩姓名取第一个字; 其余按词取首尾字母。
 */
export function PersonAvatar({
  name,
  avatarUrl,
  size,
  alt = "",
}: {
  name: string;
  avatarUrl?: string | null;
  size: PersonAvatarSize;
  alt?: string;
}) {
  const src = safeAvatarUrl(avatarUrl);
  const boxClass = cn("shrink-0 rounded-full object-cover", SIZE_CLASS[size]);
  if (src) {
    return <img src={src} alt={alt} width={size} height={size} className={boxClass} />;
  }
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center border border-accent/20 bg-accent/8 font-semibold text-accent",
        boxClass,
      )}
      aria-hidden="true"
    >
      {avatarInitials(name)}
    </span>
  );
}

const CJK_CHAR =
  /[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u3040-\u30FF\uAC00-\uD7AF]/u;

/** 中日韩姓名取首字; 拉丁等按空白分词, 单词语取首字母, 多词语取首尾词首字母。 */
export function avatarInitials(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) {
    return "";
  }
  const first = String.fromCodePoint(trimmed.codePointAt(0) ?? 0);
  if (CJK_CHAR.test(first)) {
    return first;
  }
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length === 1) {
    return (words[0]?.[0] ?? "").toUpperCase();
  }
  const firstLetter = words[0]?.[0] ?? "";
  const lastLetter = words[words.length - 1]?.[0] ?? "";
  return `${firstLetter}${lastLetter}`.toUpperCase();
}
