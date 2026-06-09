import { CheckCircle2, XCircle } from "lucide-react";

type ToastTone = "success" | "danger";

interface ToastProps {
  message: string;
  tone?: ToastTone;
}

export function Toast({ message, tone = "success" }: ToastProps) {
  const Icon = tone === "success" ? CheckCircle2 : XCircle;
  return (
    <div className={`toast toast-${tone}`} role="status">
      <Icon size={16} />
      <span>{message}</span>
    </div>
  );
}
