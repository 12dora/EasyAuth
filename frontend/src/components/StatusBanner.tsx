import { AlertCircle, CheckCircle2, Info } from "lucide-react";

import type { BadgeTone } from "../lib/status";

interface StatusBannerProps {
  tone?: BadgeTone;
  title: string;
  message?: string;
}

export function StatusBanner({ tone = "neutral", title, message }: StatusBannerProps) {
  const Icon = tone === "success" ? CheckCircle2 : tone === "danger" || tone === "warning" ? AlertCircle : Info;
  return (
    <div className={`status-banner status-${tone}`}>
      <Icon size={18} />
      <div>
        <strong>{title}</strong>
        {message ? <p>{message}</p> : null}
      </div>
    </div>
  );
}
