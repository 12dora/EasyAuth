import type { HTMLAttributes } from "react";

import type { BadgeTone } from "../lib/status";
import { toneIcon } from "./toneIcon";

type StatusBannerTone = Extract<BadgeTone, "amber" | "evergreen" | "signal" | "bond" | "neutral">;

interface StatusBannerProps {
  tone?: StatusBannerTone;
  title: string;
  message?: string;
  live?: "alert" | "status" | "off";
}

const TONE_CLASSES: Record<StatusBannerTone, string> = {
  neutral: "border-ink/15 bg-paper-soft text-ink-soft",
  amber: "border-amber/30 bg-amber/8 text-amber",
  evergreen: "border-evergreen/30 bg-evergreen/8 text-evergreen",
  signal: "border-signal/30 bg-signal/8 text-signal",
  bond: "border-bond/30 bg-bond/8 text-bond",
};

/** 变更失败横幅: 无错误时不渲染, 有 Error 或非空字符串时走 signal + alert。 */
export function MutationErrorBanner({
  title,
  error,
}: {
  title: string;
  error: Error | string | null | undefined;
}) {
  if (!error) {
    return null;
  }
  const message = typeof error === "string" ? error : error.message;
  if (!message) {
    return null;
  }
  return <StatusBanner live="alert" tone="signal" title={title} message={message} />;
}

export function StatusBanner({ tone = "neutral", title, message, live = "off" }: StatusBannerProps) {
  const Icon = toneIcon(tone);
  const liveProps: Pick<HTMLAttributes<HTMLDivElement>, "aria-live" | "role"> =
    live === "alert"
      ? { role: "alert" }
      : live === "status"
        ? { role: "status", "aria-live": "polite" }
        : {};
  return (
    <div className={`flex items-start gap-3 rounded-[3px] border px-4 py-3 ${TONE_CLASSES[tone]}`} {...liveProps}>
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        <strong className="block text-sm font-semibold leading-5">{title}</strong>
        {message ? <p className="mt-1 text-sm leading-5 text-ink-soft">{message}</p> : null}
      </div>
    </div>
  );
}
