import { CheckCircle2, XCircle } from "lucide-react";

type ToastTone = "amber" | "evergreen" | "signal" | "bond" | "neutral";

interface ToastProps {
  message: string;
  tone?: ToastTone;
}

const TONE_CLASSES: Record<ToastTone, string> = {
  neutral: "border-ink/15 bg-paper-soft text-ink-soft",
  amber: "border-[rgb(var(--amber))]/30 bg-[rgb(var(--amber))]/[0.08] text-[rgb(var(--amber))]",
  evergreen: "border-[rgb(var(--evergreen))]/30 bg-[rgb(var(--evergreen))]/[0.08] text-[rgb(var(--evergreen))]",
  signal: "border-[rgb(var(--signal))]/30 bg-[rgb(var(--signal))]/[0.08] text-[rgb(var(--signal))]",
  bond: "border-[rgb(var(--bond))]/30 bg-[rgb(var(--bond))]/[0.08] text-[rgb(var(--bond))]",
};

export function Toast({ message, tone = "evergreen" }: ToastProps) {
  const Icon = tone === "evergreen" ? CheckCircle2 : XCircle;
  return (
    <div className={`inline-flex items-center gap-2 rounded-[2px] border px-3 py-2 text-sm font-medium ${TONE_CLASSES[tone]}`} role="status">
      <Icon size={16} className="shrink-0" />
      <span className="text-ink">{message}</span>
    </div>
  );
}
