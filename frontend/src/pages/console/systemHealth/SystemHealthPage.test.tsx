import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../../../components/antd/testing";
import { ToastProvider } from "../../../components/ui/Toast";
import { SystemHealthPage } from "./SystemHealthPage";

vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

// 用量监控由 F2 提供且自带取数; 页面壳层只关心它是否被懒加载进来。
vi.mock("./UsageMonitorTab", async () => {
  const React = await import("react");
  return {
    default: function UsageMonitorTabStub() {
      return React.createElement("span", { "data-testid": "usage-monitor-tab" }, "usage");
    },
  };
});

const DEPENDENCIES_URL = "/console/api/v1/operations/system-health/dependencies";

describe("SystemHealthPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("默认打开依赖状态页签并请求重命名后的依赖接口", async () => {
    const fetchMock = dependenciesFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(screen.getByRole("heading", { name: "状态健康" })).toBeInTheDocument();
    expect(await screen.findByText("authentik")).toBeVisible();
    expect(screen.getByRole("tab", { name: "依赖状态" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "用量监控" })).toHaveAttribute("aria-selected", "false");
    expect(fetchMock).toHaveBeenCalledWith(DEPENDENCIES_URL, expect.objectContaining({ credentials: "include" }));
  });

  test("切到用量监控写进 URL 并懒加载该页签", async () => {
    vi.stubGlobal("fetch", dependenciesFetchMock());
    const user = userEvent.setup({ delay: null });

    renderPage();

    await user.click(screen.getByRole("tab", { name: "用量监控" }));

    expect(await screen.findByTestId("usage-monitor-tab")).toBeVisible();
    expect(screen.getByTestId("location-search")).toHaveTextContent("tab=usage");
    expect(screen.getByRole("tab", { name: "用量监控" })).toHaveAttribute("aria-selected", "true");
    // 页签互斥: 依赖表格必须随之卸载。
    expect(screen.queryByText("authentik")).not.toBeInTheDocument();
  });

  test("深链 ?tab=usage 直接打开用量监控, 且不请求依赖接口", async () => {
    const fetchMock = dependenciesFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    renderPage("?tab=usage");

    expect(await screen.findByTestId("usage-monitor-tab")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("?tab= 取值非法时回落依赖状态, 不报 404", async () => {
    vi.stubGlobal("fetch", dependenciesFetchMock());

    renderPage("?tab=not-real");

    expect(await screen.findByText("authentik")).toBeVisible();
    expect(screen.getByRole("tab", { name: "依赖状态" })).toHaveAttribute("aria-selected", "true");
  });

  test("方向键在页签间漫游并同步 URL", async () => {
    vi.stubGlobal("fetch", dependenciesFetchMock());
    const user = userEvent.setup({ delay: null });

    renderPage();

    const dependenciesTab = screen.getByRole("tab", { name: "依赖状态" });
    dependenciesTab.focus();
    await user.keyboard("{ArrowRight}");

    await waitFor(() => expect(screen.getByTestId("location-search")).toHaveTextContent("tab=usage"));
    expect(await screen.findByTestId("usage-monitor-tab")).toBeVisible();
  });

  test("切换页签保留 URL 上的其余查询参数", async () => {
    vi.stubGlobal("fetch", dependenciesFetchMock());
    const user = userEvent.setup({ delay: null });

    renderPage("?tab=usage&from=2026-09-01");

    await user.click(screen.getByRole("tab", { name: "依赖状态" }));

    await waitFor(() => expect(screen.getByTestId("location-search")).toHaveTextContent("from=2026-09-01"));
    expect(screen.getByTestId("location-search")).toHaveTextContent("tab=dependencies");
  });
});

function dependenciesFetchMock() {
  return vi.fn<typeof fetch>(async (input) => {
    if (String(input) === DEPENDENCIES_URL) {
      return new Response(
        JSON.stringify({
          data: [
            {
              component: "authentik",
              status: "healthy",
              summary: "正常",
              error_summary: "",
              last_checked_at: "2026-07-02T00:00:00Z",
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`Unexpected fetch: ${String(input)}`);
  });
}

function renderPage(search = "") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return renderWithAntd(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/console/operations/system-health${search}`]}>
          <LocationSearch />
          <Routes>
            <Route path="/console/operations/system-health" element={<SystemHealthPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function LocationSearch() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}
