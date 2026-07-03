import { cloneElement, isValidElement, useId } from "react";
import type { InputHTMLAttributes, ReactElement, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "../lib/cn";

interface FieldProps {
  label: string;
  labelExtra?: ReactNode;
  hint?: string;
  error?: string;
  children: ReactNode;
}

const INPUT_CLASSES =
  "w-full rounded-[2px] border border-ink/15 bg-paper-soft px-2.5 text-body text-ink transition-colors placeholder:text-ink-faint focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-50";

export function Field({ label, labelExtra, hint, error, children }: FieldProps) {
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
      <span className="flex items-center gap-1.5">
        <label className="text-label uppercase tracking-caps-wide text-ink-soft font-medium" htmlFor={inputId}>
          {label}
        </label>
        {labelExtra}
      </span>
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
