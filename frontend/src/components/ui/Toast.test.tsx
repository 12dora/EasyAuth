import { act, fireEvent, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { ToastProvider, useToast } from "./Toast";
import type { ToastTone } from "./Toast";

describe("Toast", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test("窄屏基线限制堆叠高度、底部显示并保留关闭命中区", async () => {
    render(
      <I18nProvider>
        <ToastProvider>
          <ToastProbe />
        </ToastProvider>
      </I18nProvider>,
    );

    const viewport = screen.getByTestId("toast-viewport");
    expect(viewport).toHaveClass("max-h-[min(60vh,28rem)]", "overflow-y-auto", "max-[480px]:bottom-4", "max-[480px]:top-auto");
    expect(await screen.findByRole("alert")).toHaveTextContent("失败");
    expect(screen.getByRole("status")).toHaveTextContent("完成");
    expect(screen.getAllByRole("button", { name: "关闭" })[0]).toHaveClass("min-h-6", "min-w-6");
  });

  test("卡片使用不透明纸面与语义色左边框, 右上角固定宽度且堆叠间距 8px", async () => {
    render(
      <I18nProvider>
        <ToastProvider>
          <ToastProbe />
        </ToastProvider>
      </I18nProvider>,
    );

    expect(screen.getByTestId("toast-viewport")).toHaveClass("fixed", "right-4", "top-4", "w-[360px]", "gap-2");
    const [errorToast, successToast] = await screen.findAllByTestId("toast");
    // 半透明底会与下方内容糊在一起, 卡片必须是实心 bg-paper。
    expect(errorToast).toHaveClass("bg-paper", "text-ink", "shadow-lg", "rounded-[3px]", "border-l-[3px]", "border-l-signal");
    expect(errorToast).not.toHaveClass("bg-signal/8");
    expect(successToast).toHaveClass("bg-paper", "border-l-evergreen");
  });

  test("自动关闭先进入退场态, 动画结束后才从 DOM 移除", () => {
    vi.useFakeTimers();
    render(
      <I18nProvider>
        <ToastProvider>
          <ToastProbe tone="success" title="已授予权限" />
        </ToastProvider>
      </I18nProvider>,
    );

    expect(screen.getByTestId("toast")).toHaveAttribute("data-state", "open");

    act(() => {
      vi.advanceTimersByTime(4000);
    });
    const closing = screen.getByTestId("toast");
    expect(closing).toHaveAttribute("data-state", "closing");
    expect(closing).toHaveClass("toast-card--closing");

    act(() => {
      fireEvent.animationEnd(closing);
    });
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  test("手动关闭同样播放退场动画, animationend 缺席时由超时兜底移除", () => {
    vi.useFakeTimers();
    render(
      <I18nProvider>
        <ToastProvider>
          <ToastProbe tone="error" title="授权失败" />
        </ToastProvider>
      </I18nProvider>,
    );

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    });
    expect(screen.getByTestId("toast")).toHaveAttribute("data-state", "closing");

    act(() => {
      vi.advanceTimersByTime(260);
    });
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });

  test("prefers-reduced-motion 下直接移除, 不进入退场动画", () => {
    vi.useFakeTimers();
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query.includes("prefers-reduced-motion"),
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as unknown as MediaQueryList,
    );

    render(
      <I18nProvider>
        <ToastProvider>
          <ToastProbe tone="error" title="授权失败" />
        </ToastProvider>
      </I18nProvider>,
    );

    act(() => {
      fireEvent.click(screen.getByRole("button", { name: "关闭" }));
    });
    expect(screen.queryByTestId("toast")).not.toBeInTheDocument();
  });
});

function ToastProbe({ tone, title }: { tone?: ToastTone; title?: string } = {}) {
  const toast = useToast();
  useEffect(() => {
    if (tone) {
      toast[tone](title ?? tone);
      return;
    }
    toast.error("失败");
    toast.success("完成");
  }, [toast, tone, title]);
  return null;
}
