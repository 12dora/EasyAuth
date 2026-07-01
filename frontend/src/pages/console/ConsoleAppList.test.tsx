import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsoleAppList } from "./ConsoleAppList";

describe("ConsoleAppList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.dataset.currentUserRole = "";
  });

  test("管理员看到新建应用入口", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse({ items: [] })));

    renderList();

    expect(await screen.findByRole("button", { name: "新建应用" })).toBeVisible();
  });

  test("非管理员不可见且不能提交创建", async () => {
    document.body.dataset.currentUserRole = "研发中心";
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ items: [] }));
    vi.stubGlobal("fetch", fetchMock);

    renderList();

    await screen.findByText("暂无可见应用");
    expect(screen.queryByRole("button", { name: "新建应用" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "新建应用" })).not.toBeInTheDocument();
    expect(findFetchCall(fetchMock, "/console/api/v1/apps", "POST")).toBeUndefined();
  });

  test("创建成功后跳转到新应用工作区", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps" && !init?.method) {
        return jsonResponse({ items: [] });
      }
      if (url === "/console/api/v1/apps" && init?.method === "POST") {
        return jsonResponse({ app: { id: 2, app_key: "billing", name: "Billing" } }, 201);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await user.click(await screen.findByRole("button", { name: "新建应用" }));
    await user.type(screen.getByLabelText("app_key"), "billing");
    await user.type(screen.getByLabelText("名称"), "Billing");
    await user.type(screen.getByLabelText("描述"), "Billing app");
    await user.type(screen.getByLabelText("Owner 用户 ID"), "owner-a, owner-b");
    await user.type(screen.getByLabelText("Developer 用户 ID"), "dev-a");
    await user.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => {
      const postCall = findFetchCall(fetchMock, "/console/api/v1/apps", "POST");
      expect(parseJsonBody(postCall?.[1])).toEqual({
        app_key: "billing",
        name: "Billing",
        description: "Billing app",
        owner_user_ids: ["owner-a", "owner-b"],
        developer_user_ids: ["dev-a"],
        is_active: true,
      });
    });
    expect(await screen.findByTestId("location")).toHaveTextContent("/console/apps/billing");
  });
});

function renderList() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console"]}>
        <Routes>
          <Route path="/console" element={<ConsoleAppList />} />
          <Route path="/console/apps/:appKey" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function findFetchCall(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, url: string, method: string) {
  return fetchMock.mock.calls.find(([input, init]) => String(input) === url && init?.method === method);
}

function parseJsonBody(init: RequestInit | undefined) {
  return JSON.parse(String(init?.body));
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
