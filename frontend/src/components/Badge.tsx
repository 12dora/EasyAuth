import type { BadgeTone } from "../lib/status";

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-ink/20 bg-paper-soft text-ink",
  faint: "border-ink/10 bg-paper-deep/60 text-ink-faint",
  ink: "border-ink/80 bg-ink text-paper",
  amber: "border-[rgb(var(--amber))]/40 bg-[rgb(var(--amber))]/[0.08] text-[rgb(var(--amber))]",
  evergreen: "border-[rgb(var(--evergreen))]/40 bg-[rgb(var(--evergreen))]/[0.08] text-[rgb(var(--evergreen))]",
  signal: "border-[rgb(var(--signal))]/40 bg-[rgb(var(--signal))]/[0.08] text-[rgb(var(--signal))]",
  bond: "border-[rgb(var(--bond))]/40 bg-[rgb(var(--bond))]/[0.08] text-[rgb(var(--bond))]",
};

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-[2px] border px-1.5 py-0.5 font-mono text-[10.5px] leading-4 uppercase tracking-[0.14em] ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
