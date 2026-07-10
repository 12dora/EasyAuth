import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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

  test("筛选由 URL 承载并传给运营 API(FF-21)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-requests?")) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderOperationsPage(
      "access-requests",
      "?app_key=crm&user_id=user-a&status=grant_failed&created_from=2026-07-01T08%3A30&created_to=2026-07-10T18%3A00",
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20&app_key=crm&user_id=user-a&status=grant_failed&created_from=2026-07-01T08%3A30&created_to=2026-07-10T18%3A00",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByLabelText("status")).toHaveValue("grant_failed");

    await user.clear(screen.getByLabelText("app_key"));
    await user.type(screen.getByLabelText("app_key"), "erp");

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("app_key=erp");
      expect(screen.getByTestId("location-search")).toHaveTextContent("page=1");
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("app_key=erp"),
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("展示失败原因并通过带原因确认框重试授权(FF-21)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [{
            id: 88,
            user_id: "failed-user",
            app_key: "crm",
            status: "grant_failed",
            request_type: "grant",
            failure_reason: "目录写入失败",
            submitted_at: "2026-07-02T00:00:00Z",
          }],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      if (url === "/console/api/v1/operations/access-requests/88/retry-grant" && init?.method === "POST") {
        return jsonResponse({ request_id: 88, grant_id: 9, version: 1, status: "grant_applied" });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderOperationsPage();

    expect(await screen.findByText("目录写入失败")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重试授权" }));
    const dialog = screen.getByRole("dialog", { name: "重试授权" });
    await user.click(within(dialog).getByRole("button", { name: "重试授权" }));
    expect(within(dialog).getByText("请填写操作原因")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/console/api/v1/operations/access-requests/88/retry-grant",
      expect.anything(),
    );

    await user.type(within(dialog).getByRole("textbox", { name: "原因" }), "修复目录后重试");
    await user.click(within(dialog).getByRole("button", { name: "重试授权" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests/88/retry-grant",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ reason: "修复目录后重试" }),
        }),
      );
    });
  });

  test("授权列表展示版本状态并通过带原因确认框紧急撤权(FF-21)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({
          data: [{
            id: 7,
            user_id: "risk-user",
            app_key: "crm",
            status: "active",
            version: 3,
            is_current: true,
            authorization_groups: [{
              key: "auditor",
              kind: "role",
              name: "审计员",
              expires_at: null,
            }],
            direct_grants: [{
              permission: "invoice.export",
              permission_name: "导出发票",
              scope: "GLOBAL",
              expires_at: "2026-08-01T10:00:00Z",
            }],
          }],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      if (url === "/console/api/v1/operations/emergency-revokes" && init?.method === "POST") {
        return jsonResponse({ status: "accepted", revoked_count: 1, user_id: "risk-user", app_key: "crm" });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderOperationsPage("access-grants", "?version=3&current=true");

    expect(await screen.findByText("v3")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "当前版本" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "授权组期限" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "直接权限期限" })).toBeInTheDocument();
    expect(screen.getByText("审计员 (长期)")).toBeInTheDocument();
    expect(screen.getByText(/导出发票 \[GLOBAL\].*2026/)).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&version=3&current=true",
        expect.objectContaining({ credentials: "include" }),
      );
    });

    await user.click(screen.getByRole("button", { name: "紧急撤权" }));
    const dialog = screen.getByRole("dialog", { name: "紧急撤权" });
    await user.type(within(dialog).getByRole("textbox", { name: "原因" }), "发现账号泄露");
    await user.click(within(dialog).getByRole("button", { name: "紧急撤权" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/emergency-revokes",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ user_id: "risk-user", app_key: "crm", reason: "发现账号泄露" }),
        }),
      );
    });
  });
});

function renderOperationsPage(section = "access-requests", search = "") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/console/operations/${section}${search}`]}>
        <LocationSearch />
        <Routes>
          <Route path="/console/operations/:section" element={<OperationsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationSearch() {
  const location = useLocation();
  return <span data-testid="location-search">{location.search}</span>;
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
