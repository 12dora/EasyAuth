import type { BadgeTone } from "../lib/status";

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-ink/20 bg-paper-soft text-ink",
  faint: "border-ink/10 bg-paper-deep/60 text-ink-faint",
  ink: "border-ink/80 bg-ink text-paper",
  amber: "border-amber/40 bg-amber/8 text-amber",
  evergreen: "border-evergreen/40 bg-evergreen/8 text-evergreen",
  signal: "border-signal/40 bg-signal/8 text-signal",
  bond: "border-bond/40 bg-bond/8 text-bond",
};

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-[2px] border px-1.5 py-0.5 font-mono text-micro leading-4 uppercase tracking-caps-wide ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
