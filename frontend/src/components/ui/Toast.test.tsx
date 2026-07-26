import { render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, test } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { ToastProvider, useToast } from "./Toast";

describe("Toast", () => {
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
});

function ToastProbe() {
  const toast = useToast();
  useEffect(() => {
    toast.error("失败");
    toast.success("完成");
  }, [toast]);
  return null;
}
