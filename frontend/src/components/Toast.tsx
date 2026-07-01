import { CheckCircle2, XCircle } from "lucide-react";

type ToastTone = "evergreen" | "signal";

interface ToastProps {
  message: string;
  tone?: ToastTone;
}

const TONE_CLASSES: Record<ToastTone, string> = {
  evergreen: "border-evergreen/20 bg-evergreen/10 text-evergreen",
  signal: "border-signal/20 bg-signal/10 text-signal",
};

export function Toast({ message, tone = "evergreen" }: ToastProps) {
  const Icon = tone === "evergreen" ? CheckCircle2 : XCircle;
  return (
    <div className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium ${TONE_CLASSES[tone]}`} role="status">
      <Icon size={16} className="shrink-0" />
      <span className="text-ink">{message}</span>
    </div>
  );
}
