import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="mb-6 flex items-start justify-between gap-6 border-b border-ink/12 pb-5">
      <div className="min-w-0 space-y-2">
        {eyebrow ? <p className="text-label font-semibold uppercase tracking-caps text-accent">{eyebrow}</p> : null}
        <h1 className="text-title font-semibold leading-tight text-ink">{title}</h1>
        {description ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}
