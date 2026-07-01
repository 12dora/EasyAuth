import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "ghost-danger" | "danger";
type ButtonSize = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
}

const BASE_CLASSES =
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md border text-sm font-medium transition-colors duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-ink/50 disabled:cursor-not-allowed disabled:opacity-55";

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "border-amber-ink bg-amber-ink text-white shadow-sm hover:bg-amber-ink/90",
  secondary: "border-[rgb(var(--hairline-strong))] bg-paper-deep text-ink hover:border-ink-faint hover:bg-paper",
  outline: "border-[rgb(var(--hairline-strong))] bg-paper text-ink hover:border-amber-ink/45 hover:bg-amber-ink/5",
  ghost: "border-transparent bg-transparent text-ink-soft hover:bg-ink/5 hover:text-ink",
  "ghost-danger": "border-transparent bg-transparent text-signal hover:bg-signal/10",
  danger: "border-signal bg-signal text-white shadow-sm hover:bg-signal/90",
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "h-7 px-2.5 text-xs",
  md: "h-9 px-3.5",
  lg: "h-11 px-5 text-base",
};

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

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
      className={cn(BASE_CLASSES, VARIANT_CLASSES[variant], SIZE_CLASSES[size], className)}
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
