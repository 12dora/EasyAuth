import type { ReactNode } from "react";

import { PanelSurface } from "../../../components/ui/PanelSurface";

export function StepPanel({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <PanelSurface padding="lg" className="space-y-5">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{description}</p>
      </div>
      {children}
    </PanelSurface>
  );
}

export function StepFooter({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-end gap-2 border-t border-ink/10 pt-4">{children}</div>;
}
