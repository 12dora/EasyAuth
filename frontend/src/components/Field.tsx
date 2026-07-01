import { cloneElement, isValidElement, useId } from "react";
import type { InputHTMLAttributes, ReactElement, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}

const INPUT_CLASSES =
  "w-full rounded-md border border-[rgb(var(--hairline-strong))] bg-paper px-3 text-sm text-ink shadow-sm transition-colors placeholder:text-ink-faint focus:border-amber-ink focus:outline-none focus:ring-2 focus:ring-amber-ink/15 disabled:cursor-not-allowed disabled:bg-paper-deep disabled:text-ink-faint";

function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}

export function Field({ label, hint, error, children }: FieldProps) {
  const generatedId = useId();
  const inputId = isValidElement<{ id?: string }>(children) && children.props.id ? children.props.id : generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const inputElement = isValidElement(children)
    ? cloneElement(children as ReactElement<{ id?: string; "aria-describedby"?: string }>, {
        id: inputId,
        "aria-describedby": describedBy,
      })
    : children;

  return (
    <div className="flex flex-col gap-2">
      <label className="text-[13px] font-semibold leading-none text-ink" htmlFor={inputId}>
        {label}
      </label>
      {inputElement}
      {hint ? (
        <span className="text-xs leading-5 text-ink-faint" id={hintId}>
          {hint}
        </span>
      ) : null}
      {error ? (
        <span className="text-xs font-medium leading-5 text-signal" id={errorId}>
          {error}
        </span>
      ) : null}
    </div>
  );
}

export function TextInput({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(INPUT_CLASSES, "h-9", className)} {...props} />;
}

export function TextArea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(INPUT_CLASSES, "min-h-24 py-2 leading-5", className)} {...props} />;
}

export function SelectInput({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(INPUT_CLASSES, "h-9 pr-9", className)} {...props} />;
}
