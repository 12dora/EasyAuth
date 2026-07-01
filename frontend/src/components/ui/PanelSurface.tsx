import type { HTMLAttributes, ReactNode } from "react";

interface PanelSurfaceProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
}

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function PanelSurface({ children, className, ...props }: PanelSurfaceProps) {
  return (
    <section className={cn("rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm", className)} {...props}>
      {children}
    </section>
  );
}
