import { cloneElement, isValidElement, useId } from "react";
import type { InputHTMLAttributes, ReactElement, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

import { cn } from "../lib/cn";

interface FieldProps {
  label: string;
  labelExtra?: ReactNode;
  hint?: string;
  error?: string;
  /**
   * "input"(默认): 包裹的是原生表单控件, 用 <label htmlFor> 关联并向控件注入 id/aria-describedby。
   * "group": 包裹的是自定义组件或 <div> 等不可 label 的元素, 改用 role="group" + aria-labelledby,
   *          不再把 id 静默注入到无法承载的子元素上(避免悬空 htmlFor 与被丢弃的注入)。
   */
  as?: "input" | "group";
  children: ReactNode;
}

const INPUT_CLASSES =
  "w-full rounded-[2px] border border-ink/15 bg-paper-soft px-2.5 text-body text-ink transition-colors placeholder:text-ink-faint focus:border-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-50";

export function Field({ label, labelExtra, hint, error, as = "input", children }: FieldProps) {
  const generatedId = useId();
  const isGroup = as === "group";
  const inputId = !isGroup && isValidElement<{ id?: string }>(children) && children.props.id ? children.props.id : generatedId;
  const labelId = `${inputId}-label`;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;
  const inputElement =
    !isGroup && isValidElement(children)
      ? cloneElement(children as ReactElement<{ id?: string; "aria-describedby"?: string }>, {
          id: inputId,
          "aria-describedby": describedBy,
        })
      : children;

  return (
    <div className="flex flex-col gap-2">
      <span className="flex items-center gap-1.5">
        {isGroup ? (
          <span id={labelId} className="text-label uppercase tracking-caps-wide text-ink-soft font-medium">
            {label}
          </span>
        ) : (
          <label className="text-label uppercase tracking-caps-wide text-ink-soft font-medium" htmlFor={inputId}>
            {label}
          </label>
        )}
        {labelExtra}
      </span>
      {isGroup ? (
        <div role="group" aria-labelledby={labelId} aria-describedby={describedBy}>
          {children}
        </div>
      ) : (
        inputElement
      )}
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
