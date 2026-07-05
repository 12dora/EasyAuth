import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { OperationsPage } from "./OperationsPage";

describe("OperationsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.dataset.currentUserRole = "";
    document.documentElement.dataset.currentUserRole = "";
  });

  test("系统管理员打开运营页时请求运营 API 并渲染数据", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [
            {
              id: 101,
              user_id: "user-a",
              app_key: "crm",
              status: "pending",
              request_type: "grant",
              submitted_at: "2026-07-02T00:00:00Z",
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage();

    await waitFor(() => {
      expect(screen.getByText("user-a")).toBeInTheDocument();
      expect(screen.getByText("crm")).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20",
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("审计分区按后端审计字段渲染列(FF-2)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/audit-logs?page=1&page_size=20") {
        return jsonResponse({
          data: [
            {
              actor_type: "user",
              actor_id: "admin-1",
              event_type: "grant.approved",
              target_type: "access_request",
              target_id: "req-9",
              metadata: { app_key: "crm" },
              created_at: "2026-07-02T00:00:00Z",
            },
          ],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage("audit");

    await waitFor(() => {
      expect(screen.getByRole("columnheader", { name: "事件" })).toBeInTheDocument();
      expect(screen.getByText("grant.approved")).toBeInTheDocument();
      expect(screen.getByText("user:admin-1")).toBeInTheDocument();
      expect(screen.getByText("access_request:req-9")).toBeInTheDocument();
      expect(screen.getByText("crm")).toBeInTheDocument();
    });
    // 审计行无 user_id/status 列语义, 不应出现访问申请列。
    expect(screen.queryByRole("columnheader", { name: "提交时间" })).not.toBeInTheDocument();
  });

  test("翻页触发服务端分页请求(FF-1)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [{ id: 1, user_id: "user-a", app_key: "crm", status: "pending", request_type: "grant", submitted_at: "2026-07-02T00:00:00Z" }],
          pagination: { page: 1, page_size: 20, total_items: 40, total_pages: 3 },
        });
      }
      if (url === "/console/api/v1/operations/access-requests?page=2&page_size=20") {
        return jsonResponse({
          data: [{ id: 21, user_id: "user-b", app_key: "crm", status: "pending", request_type: "grant", submitted_at: "2026-07-03T00:00:00Z" }],
          pagination: { page: 2, page_size: 20, total_items: 40, total_pages: 3 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderOperationsPage("access-requests");

    await screen.findByText("user-a");
    await user.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=2&page_size=20",
        expect.objectContaining({ credentials: "include" }),
      );
      expect(screen.getByText("user-b")).toBeInTheDocument();
    });
  });
});

function renderOperationsPage(section = "access-requests") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/console/operations/${section}`]}>
        <Routes>
          <Route path="/console/operations/:section" element={<OperationsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
