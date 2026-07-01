import { AlertCircle, CheckCircle2, Info } from "lucide-react";
import type { ReactNode } from "react";

import type { BadgeTone } from "../../lib/status";

interface PageStateProps {
  tone?: BadgeTone;
  title: string;
  description?: string;
  action?: ReactNode;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-paper-deep text-ink-soft",
  faint: "bg-paper-deep text-ink-faint",
  ink: "bg-ink/10 text-ink",
  amber: "bg-amber-ink/10 text-amber-ink",
  evergreen: "bg-evergreen/10 text-evergreen",
  signal: "bg-signal/10 text-signal",
  bond: "bg-bond/10 text-bond",
};

export function PageState({ tone = "neutral", title, description, action }: PageStateProps) {
  const Icon = tone === "evergreen" ? CheckCircle2 : tone === "signal" || tone === "amber" ? AlertCircle : Info;

  return (
    <div className="flex min-h-72 flex-col items-center justify-center px-6 py-10 text-center">
      <div className={`mb-4 flex size-10 items-center justify-center rounded-md ${TONE_CLASSES[tone]}`}>
        <Icon size={20} />
      </div>
      <h2 className="text-base font-semibold leading-6 text-ink">{title}</h2>
      {description ? <p className="mt-2 max-w-md text-sm leading-6 text-ink-soft">{description}</p> : null}
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}
