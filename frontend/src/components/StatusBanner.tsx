import { AlertCircle, CheckCircle2, Info } from "lucide-react";

import type { BadgeTone } from "../lib/status";

interface StatusBannerProps {
  tone?: BadgeTone;
  title: string;
  message?: string;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-[rgb(var(--hairline-strong))] bg-paper-deep text-ink-soft",
  faint: "border-[rgb(var(--hairline-soft))] bg-paper-deep text-ink-faint",
  ink: "border-ink/15 bg-ink/10 text-ink",
  amber: "border-amber-ink/20 bg-amber-ink/10 text-amber-ink",
  evergreen: "border-evergreen/20 bg-evergreen/10 text-evergreen",
  signal: "border-signal/20 bg-signal/10 text-signal",
  bond: "border-bond/20 bg-bond/10 text-bond",
};

export function StatusBanner({ tone = "neutral", title, message }: StatusBannerProps) {
  const Icon = tone === "evergreen" ? CheckCircle2 : tone === "signal" || tone === "amber" ? AlertCircle : Info;
  return (
    <div className={`flex items-start gap-3 rounded-md border px-4 py-3 ${TONE_CLASSES[tone]}`}>
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        <strong className="block text-sm font-semibold leading-5">{title}</strong>
        {message ? <p className="mt-1 text-sm leading-5 text-ink-soft">{message}</p> : null}
      </div>
    </div>
  );
}
