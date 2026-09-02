import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { App } from "./App";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";

vi.mock("./pages/console/ConsoleAppList", () => new Promise(() => undefined));

describe("App 未知路由策略", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("门户未知路由显示 404, 不静默重定向到门户首页", () => {
    stubResizeObserver();

    renderApp("/portal/not-real", "portal");

    expect(screen.getByRole("heading", { name: "页面没有找到" })).toBeInTheDocument();
    expect(screen.getByText("未知路由已被阻断")).toBeInTheDocument();
    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/not-real");
  });

  test("控制台未知路由显示 404, 不静默重定向到控制台首页", () => {
    stubResizeObserver();

    renderApp("/console/not-real", "console");

    expect(screen.getByRole("heading", { name: "页面没有找到" })).toBeInTheDocument();
    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/not-real");
  });

  test("控制台路由懒加载期间保留 shell 并提供忙碌状态", async () => {
    stubResizeObserver();

    renderApp("/console", "console");

    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console");
    expect(await screen.findByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { name: "正在加载页面" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation")).getByText("应用")).toBeInTheDocument();
  });
});

function renderApp(path: string, shell: "console" | "portal") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <App
              shell={shell}
              currentUser={{ id: "admin", displayName: "管理员", isSuperuser: true, role: "admin" }}
              currentUserId="admin"
            />
          </MemoryRouter>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function stubResizeObserver() {
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      disconnect() {}
    },
  );
}
