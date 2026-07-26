import type { ReactNode } from "react";

interface PageHeaderProps {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="mb-6 flex flex-col items-stretch gap-4 border-b border-ink/12 pb-5 md:flex-row md:items-start md:justify-between md:gap-6">
      <div className="min-w-0 space-y-2 md:max-w-3xl">
        {eyebrow ? <p className="text-label font-semibold uppercase tracking-caps text-accent">{eyebrow}</p> : null}
        <h1 className="text-title font-semibold leading-tight text-ink">{title}</h1>
        {description ? <p className="text-body leading-5 text-ink-soft">{description}</p> : null}
      </div>
      {actions ? <div className="flex w-full flex-wrap items-stretch gap-2 md:w-auto md:shrink-0 md:items-center md:justify-end">{actions}</div> : null}
    </header>
  );
}
