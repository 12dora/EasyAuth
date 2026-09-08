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
  persistent?: boolean;
  closing?: boolean;
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

// 卡片是不透明纸面 + 3px 语义色左边框: toast 浮在内容之上, 半透明底会与下方表格糊在一起。
const TONE_BORDER_CLASSES: Record<ToastTone, string> = {
  success: "border-l-evergreen",
  error: "border-l-signal",
  warning: "border-l-amber",
  info: "border-l-accent",
};

const TONE_ICON_CLASSES: Record<ToastTone, string> = {
  success: "text-evergreen",
  error: "text-signal",
  warning: "text-amber",
  info: "text-accent",
};

// 成功/提示停留较短, 失败默认持久直到用户关闭(关键错误可读)。
const TONE_DURATION: Record<ToastTone, number | null> = {
  success: 4000,
  info: 4000,
  warning: 5000,
  error: null,
};

// 与 styles/index.css 的 .toast-card--closing 动画时长对齐; 兜底超时留出余量,
// 覆盖 animationend 不触发的场景(jsdom、动画被打断、标签页后台化)。
const EXIT_FALLBACK_MS = 260;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const idRef = useRef(0);
  const timersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const exitTimersRef = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const remainingRef = useRef(new Map<number, number>());
  const startedAtRef = useRef(new Map<number, number>());

  const clearTimer = useCallback((id: number) => {
    const timer = timersRef.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  // 真正把卡片从 DOM 摘掉; 退场动画结束(或兜底超时)后调用。
  const remove = useCallback(
    (id: number) => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
      clearTimer(id);
      const exitTimer = exitTimersRef.current.get(id);
      if (exitTimer) {
        clearTimeout(exitTimer);
        exitTimersRef.current.delete(id);
      }
      remainingRef.current.delete(id);
      startedAtRef.current.delete(id);
    },
    [clearTimer],
  );

  // 关闭 = 先进入 closing 态播退场动画, 自动关闭与手动关闭走同一条路径。
  const dismiss = useCallback(
    (id: number) => {
      clearTimer(id);
      remainingRef.current.delete(id);
      startedAtRef.current.delete(id);
      if (prefersReducedMotion()) {
        remove(id);
        return;
      }
      if (exitTimersRef.current.has(id)) {
        return;
      }
      setToasts((current) => current.map((toast) => (toast.id === id ? { ...toast, closing: true } : toast)));
      exitTimersRef.current.set(
        id,
        setTimeout(() => remove(id), EXIT_FALLBACK_MS),
      );
    },
    [clearTimer, remove],
  );

  const schedule = useCallback(
    (id: number, duration: number) => {
      clearTimer(id);
      startedAtRef.current.set(id, Date.now());
      remainingRef.current.set(id, duration);
      const timer = setTimeout(() => dismiss(id), duration);
      timersRef.current.set(id, timer);
    },
    [clearTimer, dismiss],
  );

  const pause = useCallback(
    (id: number) => {
      const startedAt = startedAtRef.current.get(id);
      const remaining = remainingRef.current.get(id);
      if (startedAt === undefined || remaining === undefined) {
        return;
      }
      const elapsed = Date.now() - startedAt;
      remainingRef.current.set(id, Math.max(remaining - elapsed, 0));
      clearTimer(id);
    },
    [clearTimer],
  );

  const resume = useCallback(
    (id: number) => {
      const remaining = remainingRef.current.get(id);
      if (remaining === undefined || remaining <= 0) {
        return;
      }
      if (typeof document !== "undefined" && document.hidden) {
        return;
      }
      schedule(id, remaining);
    },
    [schedule],
  );

  const push = useCallback(
    (tone: ToastTone, title: string, message?: string) => {
      idRef.current += 1;
      const id = idRef.current;
      const duration = TONE_DURATION[tone];
      const persistent = duration === null;
      setToasts((current) => [...current, { id, tone, title, message, persistent }]);
      if (duration !== null) {
        schedule(id, duration);
      }
    },
    [schedule],
  );

  // 页面隐藏时暂停所有自动关闭计时。
  useEffect(() => {
    const onVisibility = () => {
      for (const id of timersRef.current.keys()) {
        if (document.hidden) {
          pause(id);
        } else {
          resume(id);
        }
      }
      if (!document.hidden) {
        for (const id of remainingRef.current.keys()) {
          if (!timersRef.current.has(id)) {
            resume(id);
          }
        }
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [pause, resume]);

  // 卸载时清空所有计时器, 避免在已卸载组件上 setState。
  useEffect(() => {
    const timers = timersRef.current;
    const exitTimers = exitTimersRef.current;
    return () => {
      timers.forEach((timer) => clearTimeout(timer));
      timers.clear();
      exitTimers.forEach((timer) => clearTimeout(timer));
      exitTimers.clear();
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
      <ToastViewport
        toasts={toasts}
        onDismiss={dismiss}
        onExited={remove}
        onPause={pause}
        onResume={resume}
      />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

function ToastViewport({
  toasts,
  onDismiss,
  onExited,
  onPause,
  onResume,
}: {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
  onExited: (id: number) => void;
  onPause: (id: number) => void;
  onResume: (id: number) => void;
}) {
  const { t } = useI18n();
  if (typeof document === "undefined") {
    return null;
  }
  return createPortal(
    <div
      className="pointer-events-none fixed right-4 top-4 z-[1100] flex max-h-[min(60vh,28rem)] w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2 overflow-y-auto max-[480px]:bottom-4 max-[480px]:top-auto max-[480px]:w-[calc(100vw-2rem)]"
      data-testid="toast-viewport"
      aria-live="polite"
      aria-relevant="additions text"
    >
      {toasts.map((toast) => (
        <ToastCard
          key={toast.id}
          toast={toast}
          dismissLabel={t("common.close")}
          onDismiss={() => onDismiss(toast.id)}
          onExited={() => onExited(toast.id)}
          onPause={() => onPause(toast.id)}
          onResume={() => onResume(toast.id)}
        />
      ))}
    </div>,
    document.body,
  );
}

function ToastCard({
  toast,
  dismissLabel,
  onDismiss,
  onExited,
  onPause,
  onResume,
}: {
  toast: ToastItem;
  dismissLabel: string;
  onDismiss: () => void;
  onExited: () => void;
  onPause: () => void;
  onResume: () => void;
}) {
  const Icon = toneIcon(BADGE_TONE[toast.tone]);
  const closing = toast.closing === true;
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      data-testid="toast"
      data-tone={toast.tone}
      data-state={closing ? "closing" : "open"}
      className={`toast-card pointer-events-auto flex items-start gap-3 rounded-[3px] border border-ink/12 border-l-[3px] bg-paper px-4 py-3 text-ink shadow-lg ${TONE_BORDER_CLASSES[toast.tone]} ${closing ? "toast-card--closing" : ""}`}
      onAnimationEnd={closing ? onExited : undefined}
      onMouseEnter={toast.persistent ? undefined : onPause}
      onMouseLeave={toast.persistent ? undefined : onResume}
      onFocus={toast.persistent ? undefined : onPause}
      onBlur={toast.persistent ? undefined : onResume}
    >
      <Icon size={18} className={`mt-0.5 shrink-0 ${TONE_ICON_CLASSES[toast.tone]}`} />
      <div className="min-w-0 flex-1">
        <strong className="block text-sm font-semibold leading-5">{toast.title}</strong>
        {toast.message ? <p className="mt-1 text-sm leading-5 text-ink-soft">{toast.message}</p> : null}
      </div>
      <button
        type="button"
        aria-label={dismissLabel}
        onClick={onDismiss}
        className="inline-flex min-h-6 min-w-6 shrink-0 items-center justify-center bg-transparent text-ink-faint transition-colors hover:text-ink"
      >
        <X size={15} aria-hidden="true" />
      </button>
    </div>
  );
}
