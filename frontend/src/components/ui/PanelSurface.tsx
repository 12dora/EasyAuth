import type { HTMLAttributes, ReactNode } from "react";

interface PanelSurfaceProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
  padding?: "none" | "sm" | "md" | "lg";
}

const PADDING_CLASSES: Record<NonNullable<PanelSurfaceProps["padding"]>, string> = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-5",
};

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function PanelSurface({ children, className, padding = "md", ...props }: PanelSurfaceProps) {
  return (
    <section className={cn("paper-card", PADDING_CLASSES[padding], className)} {...props}>
      {children}
    </section>
  );
}
