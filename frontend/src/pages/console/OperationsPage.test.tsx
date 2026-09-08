import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { OperationsPage } from "./OperationsPage";
import { ToastProvider } from "../../components/ui/Toast";
import { ANTD_TEST_TIMEOUT_MS, openFilterDropdown, openHeaderFilter, renderWithAntd } from "../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

describe("OperationsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.dataset.currentUserRole = "";
    document.documentElement.dataset.currentUserRole = "";
  });

  test("系统管理员打开运营页时请求运营 API 并渲染数据", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [
            {
              id: 101,
              user_id: "user-a",
              user_name: "胡玉琴",
              app_key: "crm",
              app_name: "CRM",
              app_alias: "客户管理",
              status: "pending",
              request_type: "grant",
              approvers: [{ user_id: "manager-1", name: "张主管" }],
              decided_by_name: "",
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
      expect(screen.getByText("胡玉琴")).toBeInTheDocument();
      expect(screen.getByText("客户管理 (CRM)")).toBeInTheDocument();
      expect(screen.getByText("张主管")).toBeInTheDocument();
      // 申请类型按文案展示, 不再暴露 grant/change/revoke/renew 这些接口取值。
      expect(screen.getByText("新增授权")).toBeInTheDocument();
      expect(screen.queryByText("grant")).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20",
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("审计分区按后端审计字段渲染列(FF-2)", async () => {
    document.body.dataset.currentUserRole = "admin";
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
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [accessRequestRow({ id: 1, user_id: "user-a", user_name: "胡玉琴" })],
          pagination: { page: 1, page_size: 20, total_items: 40, total_pages: 3 },
        });
      }
      if (url === "/console/api/v1/operations/access-requests?page=2&page_size=20") {
        return jsonResponse({
          data: [accessRequestRow({ id: 21, user_id: "user-b", user_name: "李四" })],
          pagination: { page: 2, page_size: 20, total_items: 40, total_pages: 3 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-requests");

    await screen.findByText("胡玉琴");
    await user.click(screen.getByTitle("下一页"));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=2&page_size=20",
        expect.objectContaining({ credentials: "include" }),
      );
      expect(screen.getByText("李四")).toBeInTheDocument();
    });
  });

  test("筛选由 URL 承载并传给运营 API(FF-21)", async () => {
    document.body.dataset.currentUserRole = "admin";
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
    document.body.dataset.currentUserRole = "admin";
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
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [accessRequestRow({
            id: 88,
            user_id: "failed-user",
            user_name: "王五",
            status: "grant_failed",
            failure_reason: "目录写入失败",
          })],
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
    document.body.dataset.currentUserRole = "admin";
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20") {
        listCalls += 1;
        return jsonResponse({
          data: [accessRequestRow({
            id: 91,
            user_id: "needs-retry",
            user_name: "赵六",
            status: listCalls > 1 ? "grant_failed" : "submitted",
            failure_reason: listCalls > 1 ? "目录写入失败" : "",
          })],
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

  test("授权明细按姓名与应用别名展示, 并通过带原因确认框撤销权限(FF-21)", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({
          data: [accessGrantRow()],
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

    renderOperationsPage("access-grants");

    expect(await screen.findByText("胡玉琴")).toBeInTheDocument();
    expect(screen.getByText("客户管理 (CRM)")).toBeInTheDocument();
    expect(screen.getByText("审计员")).toBeInTheDocument();
    expect(screen.getByText("2 项权限")).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
    for (const title of ["权限组", "权限详情", "过期时间"]) {
      expect(screen.getByRole("columnheader", { name: title })).toBeInTheDocument();
    }
    // 版本不再单独占列: 列表默认只给当前版本。
    expect(screen.queryByRole("columnheader", { name: /授权版本/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /当前版本/ })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&current_only=true",
        expect.objectContaining({ credentials: "include" }),
      );
    });

    await user.click(screen.getByRole("button", { name: "撤销权限" }));
    const dialog = screen.getByRole("dialog", { name: "撤销权限" });
    // 确认框按姓名与应用展示名描述操作对象, 不出现裸 id / app_key。
    expect(within(dialog).getByText(/胡玉琴/)).toBeInTheDocument();
    expect(within(dialog).getByText(/客户管理 \(CRM\)/)).toBeInTheDocument();
    await user.type(within(dialog).getByRole("textbox", { name: "原因" }), "发现账号泄露");
    await user.click(within(dialog).getByRole("button", { name: "撤销权限" }));

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

  test("授权明细勾选包含历史版本后按 current_only=false 取数", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({
          data: [accessGrantRow()],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-grants");

    await user.click(await screen.findByRole("checkbox", { name: "包含历史版本" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&current_only=false",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByTestId("location-search")).toHaveTextContent("include_history=1");
  });

  test("授权行缺少契约字段时整页报加载失败, 不静默丢字段", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        const { user_name: _dropped, ...rowWithoutUserName } = accessGrantRow();
        return jsonResponse({
          data: [rowWithoutUserName],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage("access-grants");

    expect(await screen.findByText("运营数据加载失败")).toBeInTheDocument();
    expect(screen.getByText(/user_name/)).toBeInTheDocument();
  });

  test("未接入应用清单走客户端分页(迁移前没有分页)", async () => {
    document.body.dataset.currentUserRole = "admin";
    const apps = Array.from({ length: 12 }, (_, index) => ({
      app_key: `app-${index + 1}`,
      app_name: `应用 ${index + 1}`,
      app_alias: "",
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
    document.body.dataset.currentUserRole = "admin";
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
    document.body.dataset.currentUserRole = "admin";
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
        "/console/api/v1/operations/access-grants?page=1&page_size=20&created_from=2026-07-01T08%3A30&current_only=true",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByText("创建时间")).toBeVisible();
    expect(screen.getByLabelText("创建时间 起")).toHaveValue("2026-07-01T08:30");

    await user.type(screen.getByLabelText("创建时间 止"), "2026-07-10T18:00");

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining("created_to=2026-07-10T18%3A00"),
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("授权列表的创建时间范围可一键清除, 且没有值时不显示清除按钮", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    const { unmount } = renderOperationsPage("access-grants");
    expect(await screen.findByLabelText("创建时间 起")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "清除" })).not.toBeInTheDocument();
    unmount();

    renderOperationsPage(
      "access-grants",
      "?created_from=2026-07-01T08%3A30&created_to=2026-07-10T18%3A00",
    );

    await user.click(await screen.findByRole("button", { name: "清除" }));

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).not.toHaveTextContent("created_from");
    });
    expect(screen.getByTestId("location-search")).not.toHaveTextContent("created_to");
    expect(screen.getByLabelText("创建时间 起")).toHaveValue("");
    expect(screen.queryByRole("button", { name: "清除" })).not.toBeInTheDocument();
  });

  test("撤销目标不存在时显示冲突并刷新授权列表", async () => {
    document.body.dataset.currentUserRole = "admin";
    let listCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        listCalls += 1;
        return jsonResponse({
          data: listCalls > 1 ? [] : [accessGrantRow()],
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

    await user.click(await screen.findByRole("button", { name: "撤销权限" }));
    const dialog = screen.getByRole("dialog", { name: "撤销权限" });
    await user.type(within(dialog).getByRole("textbox", { name: "原因" }), "核对风险授权");
    await user.click(within(dialog).getByRole("button", { name: "撤销权限" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("当前授权已不存在");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "撤销权限" })).not.toBeInTheDocument());
    await waitFor(() => expect(listCalls).toBeGreaterThan(1));
  });

  test("权限来自组织授权时提示无法撤销, 不留失败态", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({
          data: [accessGrantRow()],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      if (url === "/console/api/v1/operations/emergency-revokes" && init?.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "CONFLICT",
              message: "该用户在此应用的权限来自组织授权，请在组织授权中调整。",
              details: {
                reason: "department_sourced_grant",
                user_id: "risk-user",
                app_key: "crm",
                department_policy_ids: [12],
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

    await user.click(await screen.findByRole("button", { name: "撤销权限" }));
    const dialog = screen.getByRole("dialog", { name: "撤销权限" });
    await user.type(within(dialog).getByRole("textbox", { name: "原因" }), "核对风险授权");
    await user.click(within(dialog).getByRole("button", { name: "撤销权限" }));

    expect(await screen.findByText("无法撤销")).toBeInTheDocument();
    expect(screen.getByText("该权限来自组织授权，请在组织授权中调整。")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "撤销权限" })).not.toBeInTheDocument());
    // 不是一次普通失败: 页面不出撤销失败横幅。
    expect(screen.queryByText("撤销权限失败")).not.toBeInTheDocument();
  });
});

/** 访问申请行(A3: 姓名 / 应用名 / 审批人姓名随行下发)。 */
function accessRequestRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    user_id: "user-a",
    user_name: "胡玉琴",
    app_key: "crm",
    app_name: "CRM",
    app_alias: "客户管理",
    status: "submitted",
    request_type: "grant",
    approvers: [{ user_id: "manager-1", name: "张主管" }],
    decided_by_name: "",
    failure_reason: "",
    submitted_at: "2026-07-02T00:00:00Z",
    ...overrides,
  };
}

/** 授权明细行(A1: 后端 serialize_access_grant_row 的形状)。 */
function accessGrantRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 7,
    version: 3,
    is_current: true,
    status: "active",
    user_id: "risk-user",
    user_name: "胡玉琴",
    app_key: "crm",
    app_name: "CRM",
    app_alias: "客户管理",
    grant_type: "timed",
    grant_expires_at: "2026-08-01T10:00:00Z",
    authorization_groups: [
      { key: "auditor", kind: "role", name: "审计员", expires_at: null, source: "user" },
    ],
    direct_grants: [
      {
        permission: "invoice.export",
        permission_name: "导出发票",
        scope: "GLOBAL",
        scope_name: "全局",
        expires_at: "2026-08-01T10:00:00Z",
        source: "user",
      },
    ],
    groups: [{ key: "auditor", kind: "role", name: "审计员" }],
    grants: [
      {
        permission: "invoice.view",
        scope: "GLOBAL",
        source_type: "group",
        source_key: "auditor",
        permission_name: "查看发票",
        permission_name_en: "View invoice",
        scope_name: "全局",
        scope_name_en: "Global",
      },
      {
        permission: "invoice.export",
        scope: "GLOBAL",
        source_type: "direct",
        source_key: "",
        permission_name: "导出发票",
        permission_name_en: "Export invoice",
        scope_name: "全局",
        scope_name_en: "Global",
      },
    ],
    ...overrides,
  };
}

function renderOperationsPage(section = "access-requests", search = "") {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return renderWithAntd(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[`/console/operations/${section}${search}`]}>
          <LocationSearch />
          <Routes>
            <Route path="/console/operations/:section" element={<OperationsPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

async function openFilterOf(user: ReturnType<typeof userEvent.setup>, header: HTMLElement) {
  await user.click(header.querySelector(".ant-table-filter-trigger") as HTMLElement);
  return await openFilterDropdown();
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
