import { AlertCircle, CheckCircle2, Info } from "lucide-react";

import type { BadgeTone } from "../lib/status";

type StatusBannerTone = Extract<BadgeTone, "amber" | "evergreen" | "signal" | "bond" | "neutral">;

interface StatusBannerProps {
  tone?: StatusBannerTone;
  title: string;
  message?: string;
}

const TONE_CLASSES: Record<StatusBannerTone, string> = {
  neutral: "border-ink/15 bg-paper-soft text-ink-soft",
  amber: "border-[rgb(var(--amber))]/30 bg-[rgb(var(--amber))]/[0.08] text-[rgb(var(--amber))]",
  evergreen: "border-[rgb(var(--evergreen))]/30 bg-[rgb(var(--evergreen))]/[0.08] text-[rgb(var(--evergreen))]",
  signal: "border-[rgb(var(--signal))]/30 bg-[rgb(var(--signal))]/[0.08] text-[rgb(var(--signal))]",
  bond: "border-[rgb(var(--bond))]/30 bg-[rgb(var(--bond))]/[0.08] text-[rgb(var(--bond))]",
};

export function StatusBanner({ tone = "neutral", title, message }: StatusBannerProps) {
  const Icon = tone === "evergreen" ? CheckCircle2 : tone === "signal" || tone === "amber" ? AlertCircle : Info;
  return (
    <div className={`flex items-start gap-3 rounded-[3px] border px-4 py-3 ${TONE_CLASSES[tone]}`}>
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        <strong className="block text-sm font-semibold leading-5">{title}</strong>
        {message ? <p className="mt-1 text-sm leading-5 text-ink-soft">{message}</p> : null}
      </div>
    </div>
  );
}
