import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  subtitle?: string;
  meta?: ReactNode;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, subtitle, meta, actions }: PageHeaderProps) {
  const supportingText = subtitle ?? description;

  return (
    <header className="flex items-start justify-between gap-6 border-b border-[rgb(var(--hairline))] pb-5">
      <div className="min-w-0 space-y-2">
        {eyebrow ? <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-amber-ink">{eyebrow}</p> : null}
        <h1 className="text-[26px] font-semibold leading-tight text-ink">{title}</h1>
        {supportingText ? <p className="max-w-3xl text-[13px] leading-5 text-ink-soft">{supportingText}</p> : null}
        {meta ? <div className="text-[11px] font-medium leading-4 text-ink-faint">{meta}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}
