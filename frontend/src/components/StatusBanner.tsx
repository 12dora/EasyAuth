import type { BadgeTone } from "../lib/status";
import { toneIcon } from "./toneIcon";

type StatusBannerTone = Extract<BadgeTone, "amber" | "evergreen" | "signal" | "bond" | "neutral">;

interface StatusBannerProps {
  tone?: StatusBannerTone;
  title: string;
  message?: string;
}

const TONE_CLASSES: Record<StatusBannerTone, string> = {
  neutral: "border-ink/15 bg-paper-soft text-ink-soft",
  amber: "border-amber/30 bg-amber/8 text-amber",
  evergreen: "border-evergreen/30 bg-evergreen/8 text-evergreen",
  signal: "border-signal/30 bg-signal/8 text-signal",
  bond: "border-bond/30 bg-bond/8 text-bond",
};

export function StatusBanner({ tone = "neutral", title, message }: StatusBannerProps) {
  const Icon = toneIcon(tone);
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
