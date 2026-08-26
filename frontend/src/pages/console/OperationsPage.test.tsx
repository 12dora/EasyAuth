import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { AppConfigProvider } from "../../components/antd/AppConfigProvider";
import { I18nProvider } from "../../i18n/I18nProvider";
import { OperationsPage } from "./OperationsPage";

// antd Table 在 jsdom 里每次筛选/翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: 20000 });

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

  test("未知运营分区显示 404 且不回退访问申请列表", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage("not-real");

    expect(await screen.findByText("页面没有找到")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
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
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-requests");

    await screen.findByText("user-a");
    await user.click(screen.getByTitle("下一页"));

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
    const user = userEvent.setup({ delay: null });

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
    // URL 上的筛选条件反映为表头筛选的激活态。
    await waitFor(() => {
      expect(columnHeader("状态").querySelector(".ant-table-filter-trigger")).toHaveClass("active");
      expect(columnHeader("应用").querySelector(".ant-table-filter-trigger")).toHaveClass("active");
      expect(columnHeader("提交时间").querySelector(".ant-table-filter-trigger")).toHaveClass("active");
    });

    const appFilter = await openHeaderFilter(user, "应用");
    const keyword = within(appFilter).getByLabelText("筛选关键字");
    await user.clear(keyword);
    await user.type(keyword, "erp");
    await user.click(within(appFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("app_key=erp");
      expect(screen.getByTestId("location-search")).toHaveTextContent("page=1");
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("app_key=erp"),
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("表头的时间范围筛选写回 URL 的 created_from/created_to(FF-21)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/audit-logs?")) {
        return jsonResponse({
          data: [{
            actor_type: "user",
            actor_id: "admin-1",
            event_type: "grant.approved",
            target_type: "access_request",
            target_id: "req-9",
            metadata: { app_key: "crm" },
            created_at: "2026-07-02T00:00:00Z",
          }],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("audit");

    await screen.findByText("grant.approved");

    const timeFilter = await openHeaderFilter(user, "时间");
    await user.type(within(timeFilter).getByLabelText("created_from"), "2026-07-01T08:30");
    await user.type(within(timeFilter).getByLabelText("created_to"), "2026-07-10T18:00");
    await user.click(within(timeFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/console/api/v1/audit-logs?page=1&page_size=20&created_from=2026-07-01T08%3A30&created_to=2026-07-10T18%3A00",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByTestId("location-search")).toHaveTextContent("created_from=2026-07-01T08%3A30");
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
    const user = userEvent.setup({ delay: null });

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

  test("审批已提交但授权落地失败时关闭弹窗并刷新申请列表", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        listCalls += 1;
        return jsonResponse({
          data: [{
            id: 91,
            user_id: "needs-retry",
            app_key: "crm",
            status: listCalls > 1 ? "grant_failed" : "submitted",
            request_type: "grant",
            failure_reason: listCalls > 1 ? "目录写入失败" : "",
            submitted_at: "2026-07-02T00:00:00Z",
          }],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      if (url === "/console/api/v1/operations/access-requests/91/approve" && init?.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "SEMANTIC_VALIDATION_ERROR",
              message: "目录写入失败",
              details: {
                decision_committed: true,
                request_id: 91,
                status: "grant_failed",
                approval: { id: 91, status: "approved" },
              },
            },
          },
          422,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage();

    await user.click(await screen.findByRole("button", { name: "同意" }));
    await user.click(screen.getByRole("button", { name: "确认同意" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("审批已通过，但授权未落地");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "同意申请" })).not.toBeInTheDocument());
    await waitFor(() => expect(listCalls).toBeGreaterThan(1));
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
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-grants", "?version=3&current=true");

    expect(await screen.findByText("v3")).toBeInTheDocument();
    // 该列带枚举筛选, 表头可访问名里还会包含筛选图标的 label。
    expect(screen.getByRole("columnheader", { name: /当前版本/ })).toBeInTheDocument();
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

  test("未接入应用清单走客户端分页(迁移前没有分页)", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const apps = Array.from({ length: 12 }, (_, index) => ({
      app_key: `app-${index + 1}`,
      app_name: `应用 ${index + 1}`,
      blocked_task_count: index + 1,
    }));
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/lifecycle/handover-blocked-apps") {
        return jsonResponse({ app_count: apps.length, task_count: 78, apps });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("blocked-apps");

    expect(await screen.findByText("应用 1")).toBeVisible();
    expect(screen.getByText("第 1-10 条 / 共 12 条")).toBeInTheDocument();
    expect(screen.queryByText("应用 11")).not.toBeInTheDocument();

    await user.click(screen.getByTitle("2"));

    expect(await screen.findByText("应用 11")).toBeVisible();
    // 客户端分页: 翻页不会再打后端。
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("依赖健康分区在客户端筛选状态且不请求后端", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/operations/dependency-health") {
        return jsonResponse({
          data: [
            { component: "authentik", status: "healthy", summary: "正常", error_summary: "", last_checked_at: "2026-07-02T00:00:00Z" },
            { component: "dingtalk", status: "unhealthy", summary: "调用失败", error_summary: "HTTP 500", last_checked_at: "2026-07-02T00:00:00Z" },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("dependency-health");

    expect(await screen.findByText("authentik")).toBeVisible();

    const statusFilter = await openHeaderFilter(user, "状态");
    await user.click(within(statusFilter).getByText("异常"));
    await user.click(within(statusFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(screen.queryByText("authentik")).not.toBeInTheDocument());
    expect(screen.getByText("dingtalk")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("授权列表的创建时间范围仍由表格上方控件承载并写回 URL", async () => {
    // 授权列表载荷里没有 created_at 字段, 没有时间列可以挂表头筛选,
    // 因此这是全站唯一保留在表格上方的筛选控件。
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-grants", "?created_from=2026-07-01T08%3A30");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&created_from=2026-07-01T08%3A30",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByLabelText("created_from")).toHaveValue("2026-07-01T08:30");

    await user.type(screen.getByLabelText("created_to"), "2026-07-10T18:00");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("created_to=2026-07-10T18%3A00"),
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("紧急撤权目标不存在时显示冲突并刷新授权列表", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        listCalls += 1;
        return jsonResponse({
          data: listCalls > 1 ? [] : [{
            id: 7,
            user_id: "risk-user",
            app_key: "crm",
            status: "active",
            version: 3,
            is_current: true,
            authorization_groups: [],
            direct_grants: [],
          }],
          pagination: { page: 1, page_size: 20, total_items: listCalls > 1 ? 0 : 1, total_pages: 1 },
        });
      }
      if (url === "/console/api/v1/operations/emergency-revokes" && init?.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "CONFLICT",
              message: "当前没有可撤销的有效授权。",
              details: {
                reason: "active_grant_not_found",
                user_id: "risk-user",
                app_key: "crm",
              },
            },
          },
          409,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-grants");

    await user.click(await screen.findByRole("button", { name: "紧急撤权" }));
    const dialog = screen.getByRole("dialog", { name: "紧急撤权" });
    await user.type(within(dialog).getByRole("textbox", { name: "原因" }), "核对风险授权");
    await user.click(within(dialog).getByRole("button", { name: "紧急撤权" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("当前授权已不存在");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "紧急撤权" })).not.toBeInTheDocument());
    await waitFor(() => expect(listCalls).toBeGreaterThan(1));
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
      <I18nProvider>
        <AppConfigProvider>
          <MemoryRouter initialEntries={[`/console/operations/${section}${search}`]}>
            <LocationSearch />
            <Routes>
              <Route path="/console/operations/:section" element={<OperationsPage />} />
            </Routes>
          </MemoryRouter>
        </AppConfigProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

/** 打开某一列的表头筛选下拉, 返回当前可见的下拉内容。 */
async function openHeaderFilter(user: ReturnType<typeof userEvent.setup>, columnTitle: string) {
  const header = [...document.querySelectorAll("th.ant-table-cell")].find((cell) =>
    cell.textContent?.startsWith(columnTitle),
  );
  expect(header).toBeDefined();
  return await openFilterOf(user, header as HTMLElement);
}

async function openFilterOf(user: ReturnType<typeof userEvent.setup>, header: HTMLElement) {
  await user.click(header.querySelector(".ant-table-filter-trigger") as HTMLElement);
  return await waitFor(() => {
    const dropdown = document.querySelector(".ant-dropdown:not(.ant-dropdown-hidden) .ant-table-filter-dropdown");
    expect(dropdown).not.toBeNull();
    return dropdown as HTMLElement;
  });
}

function columnHeader(columnTitle: string): HTMLElement {
  const header = [...document.querySelectorAll("th.ant-table-cell")].find((cell) =>
    cell.textContent?.startsWith(columnTitle),
  );
  expect(header).toBeDefined();
  return header as HTMLElement;
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
