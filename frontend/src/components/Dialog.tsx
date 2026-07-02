import { X } from "lucide-react";
import { useEffect, useId } from "react";
import { createPortal } from "react-dom";
import type { ReactNode } from "react";

type DialogSize = "sm" | "md" | "lg" | "xl";

interface DialogProps {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  size?: DialogSize;
  eyebrow?: ReactNode;
}

const SIZE_CLASSES: Record<DialogSize, string> = {
  sm: "max-w-md",
  md: "max-w-xl",
  lg: "max-w-3xl",
  xl: "max-w-5xl",
};

export function Dialog({ title, children, footer, onClose, size = "md", eyebrow }: DialogProps) {
  const titleId = useId();
  useDialogEffects(onClose);

  if (typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div className="fixed inset-0 z-[1000] flex items-start justify-center overflow-y-auto px-4 py-10" role="presentation">
      <button
        type="button"
        aria-label="关闭弹窗遮罩"
        className="fixed inset-0 cursor-default bg-ink/40 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div
        className={`paper-card relative z-10 w-full overflow-hidden rounded-[3px] p-0 ${SIZE_CLASSES[size]}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
          <header className="flex items-start justify-between gap-4 border-b border-ink/12 px-6 pb-4 pt-5">
            <div>
              {eyebrow ? <div className="eyebrow mb-1.5">{eyebrow}</div> : null}
              <h2 id={titleId} className="text-[22px] font-semibold leading-tight text-ink">
                {title}
              </h2>
            </div>
            <button
              type="button"
              className="-mr-1 inline-flex size-8 items-center justify-center rounded-[2px] border border-transparent bg-transparent text-ink-soft transition-colors hover:bg-ink/5 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-ink/50"
              onClick={onClose}
              aria-label="关闭弹窗"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </header>
          <div className="max-h-[85vh] overflow-y-auto px-6 py-5">{children}</div>
          {footer ? (
            <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-ink/12 bg-paper-deep/30 px-6 py-4">
              {footer}
            </footer>
          ) : null}
      </div>
    </div>,
    document.body,
  );
}

function useDialogEffects(onClose: () => void) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    lockDialogScroll();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      unlockDialogScroll();
    };
  }, [onClose]);
}

let scrollLockDepth = 0;
let scrollSnapshot: { htmlOverflow: string; bodyOverflow: string } | null = null;

function lockDialogScroll() {
  scrollLockDepth += 1;
  if (scrollLockDepth > 1) {
    return;
  }
  scrollSnapshot = {
    htmlOverflow: document.documentElement.style.overflow,
    bodyOverflow: document.body.style.overflow,
  };
  document.documentElement.style.overflow = "hidden";
  document.body.style.overflow = "hidden";
}

function unlockDialogScroll() {
  scrollLockDepth = Math.max(0, scrollLockDepth - 1);
  if (scrollLockDepth > 0 || !scrollSnapshot) {
    return;
  }
  document.documentElement.style.overflow = scrollSnapshot.htmlOverflow;
  document.body.style.overflow = scrollSnapshot.bodyOverflow;
  scrollSnapshot = null;
}
