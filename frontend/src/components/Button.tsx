import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "../lib/cn";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "ghost-danger" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
}

export const BUTTON_BASE_CLASSES =
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-[2px] border font-medium transition-all duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent/50 disabled:cursor-not-allowed disabled:opacity-55";

export const BUTTON_VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "border-ink bg-ink text-paper hover:bg-ink/90 active:[transform:translateY(1px)]",
  secondary: "border-accent bg-accent text-paper hover:bg-accent/90 active:[transform:translateY(1px)]",
  outline:
    "border-ink/30 bg-transparent text-ink hover:border-ink/60 hover:bg-ink/[0.04] active:[transform:translateY(1px)]",
  ghost:
    "border-transparent bg-transparent text-ink-soft hover:bg-ink/[0.04] hover:text-ink active:[transform:translateY(1px)]",
  "ghost-danger":
    "border-transparent bg-transparent text-signal hover:bg-signal/10 active:[transform:translateY(1px)]",
  danger: "border-signal bg-signal text-paper hover:bg-signal/90 active:[transform:translateY(1px)]",
};

export const BUTTON_SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-caption tracking-wide",
  md: "h-9 px-3.5 text-body tracking-wide",
  lg: "h-11 px-5 text-sm tracking-wide",
};

export function Button({
  className,
  disabled,
  icon,
  loading = false,
  size = "md",
  variant = "outline",
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(BUTTON_BASE_CLASSES, BUTTON_VARIANT_CLASSES[variant], BUTTON_SIZE_CLASSES[size], className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <span
          className="size-3 animate-spin rounded-full border border-current border-t-transparent"
          data-slot="spinner"
          aria-hidden="true"
        />
      ) : icon ? (
        <span className="inline-flex size-4 items-center justify-center" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children ? <span>{children}</span> : null}
    </button>
  );
}
