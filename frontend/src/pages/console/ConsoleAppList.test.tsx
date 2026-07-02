import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

    expect(await screen.findByRole("button", { name: "新建" })).toBeVisible();
  });

  test("管理员可以在列表行内启停和删除应用", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps" && !init?.method) {
        return jsonResponse({
          items: [
            { id: 1, app_key: "crm", name: "CRM", owners: ["owner-a"], is_active: true, updated_at: "2026-07-01T09:00:00Z" },
            { id: 2, app_key: "billing", name: "Billing", owners: ["owner-b"], is_active: false, updated_at: "2026-07-01T09:00:00Z" },
          ],
        });
      }
      if (url === "/console/api/v1/apps/crm" && init?.method === "PATCH") {
        return jsonResponse({ ok: true });
      }
      if (url === "/console/api/v1/apps/billing" && init?.method === "PATCH") {
        return jsonResponse({ ok: true });
      }
      if (url === "/console/api/v1/apps/crm" && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    const crmRow = await screen.findByRole("row", { name: /CRM/ });
    const billingRow = screen.getByRole("row", { name: /Billing/ });

    await user.click(within(crmRow).getByRole("button", { name: "停用" }));
    await user.click(within(billingRow).getByRole("button", { name: "启用" }));
    await user.click(within(crmRow).getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(parseJsonBody(findFetchCall(fetchMock, "/console/api/v1/apps/crm", "PATCH")?.[1])).toEqual({ is_active: false });
      expect(parseJsonBody(findFetchCall(fetchMock, "/console/api/v1/apps/billing", "PATCH")?.[1])).toEqual({ is_active: true });
      expect(findFetchCall(fetchMock, "/console/api/v1/apps/crm", "DELETE")).toBeDefined();
    });
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

    await user.click(await screen.findByRole("button", { name: "新建" }));
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
