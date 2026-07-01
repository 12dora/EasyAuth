import { X } from "lucide-react";
import { useId } from "react";
import type { ReactNode } from "react";

import { Button } from "./Button";

type DialogSize = "sm" | "md" | "lg" | "xl";

interface DialogProps {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  size?: DialogSize;
}

const SIZE_CLASSES: Record<DialogSize, string> = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
  xl: "max-w-4xl",
};

export function Dialog({ title, children, footer, onClose, size = "md" }: DialogProps) {
  const titleId = useId();

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/35 px-4 py-10 backdrop-blur-sm" role="presentation">
      <div
        className={`max-h-[calc(100vh-5rem)] w-full overflow-hidden rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper shadow-2xl ${SIZE_CLASSES[size]}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="flex min-h-14 items-center justify-between gap-4 border-b border-[rgb(var(--hairline))] px-5 py-3">
          <h2 id={titleId} className="text-base font-semibold leading-6 text-ink">
            {title}
          </h2>
          <Button variant="ghost" size="sm" icon={<X size={16} />} onClick={onClose} aria-label="关闭弹窗" />
        </header>
        <div className="max-h-[calc(100vh-13rem)] overflow-auto px-5 py-5">{children}</div>
        {footer ? (
          <footer className="flex items-center justify-end gap-2 border-t border-[rgb(var(--hairline))] bg-paper-deep px-5 py-4">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  );
}
