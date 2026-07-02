import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";

import type { BadgeTone } from "../../lib/status";

interface PageStateProps {
  tone?: BadgeTone;
  title: string;
  description?: string;
  action?: ReactNode;
  iconFrame?: boolean;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "text-ink-soft",
  faint: "text-ink-faint",
  ink: "text-ink",
  amber: "text-[rgb(var(--amber))]",
  evergreen: "text-[rgb(var(--evergreen))]",
  signal: "text-[rgb(var(--signal))]",
  bond: "text-[rgb(var(--bond))]",
};

export function PageState({ tone = "neutral", title, description, action, iconFrame = true }: PageStateProps) {
  const Icon = tone === "evergreen" ? CheckCircle2 : tone === "signal" || tone === "amber" ? AlertCircle : Info;
  const icon = <Icon size={20} />;

  return (
    <div className="flex min-h-72 flex-col items-center justify-center rounded-[3px] border border-ink/15 bg-paper-soft px-6 py-10 text-center">
      {iconFrame ? (
        <div className={`mb-4 flex size-10 items-center justify-center rounded-[2px] bg-paper-deep ${TONE_CLASSES[tone]}`}>
          {icon}
        </div>
      ) : (
        <div className={`mb-4 inline-flex ${TONE_CLASSES[tone]}`}>{icon}</div>
      )}
      <h2 className="text-base font-semibold leading-6 text-ink">{title}</h2>
      {description ? <p className="mt-2 max-w-md text-sm leading-6 text-ink-soft">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
