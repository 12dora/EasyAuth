import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-md border border-dashed border-[rgb(var(--hairline-strong))] bg-paper-deep px-6 py-8 text-center">
      {icon ? <div className="mb-3 flex size-9 items-center justify-center rounded-md bg-paper text-ink-faint">{icon}</div> : null}
      <h2 className="text-sm font-semibold leading-5 text-ink">{title}</h2>
      {description ? <p className="mt-1 max-w-md text-sm leading-5 text-ink-soft">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
