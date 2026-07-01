import type { BadgeTone } from "../lib/status";

interface BadgeProps {
  tone?: BadgeTone;
  children: React.ReactNode;
}

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "border-[rgb(var(--hairline-strong))] bg-paper text-ink-soft",
  faint: "border-[rgb(var(--hairline-soft))] bg-paper-deep text-ink-faint",
  ink: "border-ink/15 bg-ink/10 text-ink",
  amber: "border-amber-ink/20 bg-amber-ink/10 text-amber-ink",
  evergreen: "border-evergreen/20 bg-evergreen/10 text-evergreen",
  signal: "border-signal/20 bg-signal/10 text-signal",
  bond: "border-bond/20 bg-bond/10 text-bond",
};

export function Badge({ tone = "neutral", children }: BadgeProps) {
  return (
    <span
      className={`inline-flex h-6 items-center rounded-md border px-2 text-[11px] font-semibold leading-none ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
