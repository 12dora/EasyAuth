import { X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "../../i18n/I18nProvider";
import type { BadgeTone } from "../../lib/status";
import { toneIcon } from "../toneIcon";

export type ToastTone = "success" | "error" | "warning" | "info";

interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  message?: string;
}

export interface ToastApi {
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
  dismiss: (id: number) => void;
}

const NOOP: ToastApi = {
  success: () => {},
  error: () => {},
  warning: () => {},
  info: () => {},
  dismiss: () => {},
};

// 无 Provider 时(组件单测直接渲染)toast 调用降级为 no-op, 对齐 I18nProvider 的默认上下文约定。
const ToastContext = createContext<ToastApi>(NOOP);

const BADGE_TONE: Record<ToastTone, BadgeTone> = {
  success: "evergreen",
  error: "signal",
  warning: "amber",
  info: "neutral",
};

// 与 StatusBanner 的配色保持一致, 让 toast 与内联提示观感统一。
const TONE_CLASSES: Record<ToastTone, string> = {
  success: "border-evergreen/30 bg-evergreen/8 text-evergreen",
  error: "border-signal/30 bg-signal/8 text-signal",
  warning: "border-amber/30 bg-amber/8 text-amber",
  info: "border-ink/15 bg-paper-soft text-ink-soft",
};

// 成功/提示停留较短, 失败停留更久以便读清错误详情。
const TONE_DURATION: Record<ToastTone, number> = {
  success: 4000,
  info: 4000,
  warning: 5000,
  error: 6000,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (tone: ToastTone, title: string, message?: string) => {
      idRef.current += 1;
      const id = idRef.current;
      setToasts((current) => [...current, { id, tone, title, message }]);
      const timer = setTimeout(() => dismiss(id), TONE_DURATION[tone]);
      timersRef.current.set(id, timer);
    },
    [dismiss],
  );

  // 卸载时清空所有计时器, 避免在已卸载组件上 setState。
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
    };
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      success: (title, message) => push("success", title, message),
      error: (title, message) => push("error", title, message),
      warning: (title, message) => push("warning", title, message),
      info: (title, message) => push("info", title, message),
      dismiss,
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

function ToastViewport({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: number) => void }) {
  const { t } = useI18n();
  if (typeof document === "undefined") {
    return null;
  }
  return createPortal(
    <div
      className="pointer-events-none fixed right-4 top-4 z-[1100] flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2"
      data-testid="toast-viewport"
    >
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} dismissLabel={t("common.close")} onDismiss={() => onDismiss(toast.id)} />
      ))}
    </div>,
    document.body,
  );
}

function ToastCard({ toast, dismissLabel, onDismiss }: { toast: ToastItem; dismissLabel: string; onDismiss: () => void }) {
  const Icon = toneIcon(BADGE_TONE[toast.tone]);
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      data-testid="toast"
      data-tone={toast.tone}
      className={`pointer-events-auto flex items-start gap-3 rounded-[3px] border px-4 py-3 shadow-lg ${TONE_CLASSES[toast.tone]}`}
    >
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <strong className="block text-sm font-semibold leading-5">{toast.title}</strong>
        {toast.message ? <p className="mt-1 text-sm leading-5 text-ink-soft">{toast.message}</p> : null}
      </div>
      <button
        type="button"
        aria-label={dismissLabel}
        onClick={onDismiss}
        className="shrink-0 bg-transparent text-ink-faint transition-colors hover:text-ink"
      >
        <X size={15} aria-hidden="true" />
      </button>
    </div>
  );
}
