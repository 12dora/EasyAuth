import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-[3px] border border-ink/15 bg-paper-soft px-6 py-8 text-center">
      {icon ? <div className="mb-3 flex size-9 items-center justify-center rounded-[2px] bg-paper-deep text-ink-faint">{icon}</div> : null}
      <p className="text-sm font-semibold leading-5 text-ink">{title}</p>
      {description ? <p className="mt-1 max-w-md text-sm leading-5 text-ink-soft">{description}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}
