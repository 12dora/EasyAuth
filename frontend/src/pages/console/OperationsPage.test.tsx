import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import dayjs from "dayjs";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { formatDateRangeBound } from "../../components/antd/AppTable";
import { OperationsPage } from "./OperationsPage";
import { ToastProvider } from "../../components/ui/Toast";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  openFilterDropdown,
  openHeaderFilter,
  renderWithAntd,
  sortByColumn,
} from "../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

describe("OperationsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    document.body.dataset.currentUserRole = "";
    document.documentElement.dataset.currentUserRole = "";
  });

  test("系统管理员打开运营页时请求运营 API 并渲染数据", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted") {
        return jsonResponse({
          data: [
            {
              id: 101,
              user_id: "user-a",
              user_name: "胡玉琴",
              user_department: "捷发-安环部",
              app_key: "crm",
              app_name: "CRM",
              app_alias: "客户管理",
              status: "pending",
              request_type: "grant",
              approvers: [{ user_id: "manager-1", name: "张主管", account_kind: "directory" }],
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
      expect(screen.getByText("捷发-安环部")).toBeInTheDocument();
      expect(screen.queryByText("user-a")).not.toBeInTheDocument();
      expect(screen.getByText("客户管理 (CRM)")).toBeInTheDocument();
      expect(screen.getByText("张主管")).toBeInTheDocument();
      // 申请类型按文案展示, 不再暴露 grant/change/revoke/renew 这些接口取值。
      expect(screen.getByText("新增授权")).toBeInTheDocument();
      expect(screen.queryByText("grant")).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted",
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("审计分区按后端审计字段渲染列(FF-2)", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/audit-logs?page=1&page_size=20") {
        return jsonResponse({
          data: [auditLogRow()],
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

  test("审计操作者有 actor_person 时按姓名与部门展示, 不暴露裸 ID", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/audit-logs?page=1&page_size=20") {
        return jsonResponse({
          data: [
            auditLogRow({
              actor_person: {
                user_id: "admin-1",
                name: "李管理员",
                department: "捷发-信息部",
                account_kind: "directory",
              },
            }),
          ],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage("audit");

    expect(await screen.findByText("李管理员")).toBeInTheDocument();
    expect(screen.getByText("捷发-信息部")).toBeInTheDocument();
    expect(screen.queryByText("user:admin-1")).not.toBeInTheDocument();
    expect(screen.queryByText("admin-1")).not.toBeInTheDocument();
  });

  test("审计行缺少 actor_person 时整页报加载失败, 不静默丢字段", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/console/api/v1/audit-logs?page=1&page_size=20") {
        const { actor_person: _dropped, ...rowWithoutActorPerson } = auditLogRow();
        return jsonResponse({
          data: [rowWithoutActorPerson],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage("audit");

    expect(await screen.findByText("运营数据加载失败")).toBeInTheDocument();
    expect(screen.getByText(/actor_person/)).toBeInTheDocument();
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
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted") {
        return jsonResponse({
          data: [accessRequestRow({ id: 1, user_id: "user-a", user_name: "胡玉琴" })],
          pagination: { page: 1, page_size: 20, total_items: 40, total_pages: 3 },
        });
      }
      if (url === "/console/api/v1/operations/access-requests?page=2&page_size=20&status=submitted") {
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
        "/console/api/v1/operations/access-requests?page=2&page_size=20&status=submitted",
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

  test("待审批页默认只取 submitted, 表头筛选显示默认口径", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = accessRequestsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-requests");

    await screen.findByText("胡玉琴");
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted",
      expect.objectContaining({ credentials: "include" }),
    );
    expect(screen.getByText("仅显示待审批的申请；可在状态筛选中查看历史。")).toBeInTheDocument();
    // 默认口径必须在表头看得见: 状态列显示为已筛选, 下拉里选中「等待审批」。
    expect(columnHeader("状态").querySelector(".ant-table-filter-trigger")).toHaveClass("active");
    const statusFilter = await openHeaderFilter(user, "状态");
    expect(selectedFilterOption(statusFilter)).toBe("等待审批");
  });

  test("状态筛选选其他状态时按该状态取数, 选「全部」才不带 status", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = accessRequestsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-requests");
    await screen.findByText("胡玉琴");

    const rejectedFilter = await openHeaderFilter(user, "状态");
    await user.click(within(rejectedFilter).getByText("已拒绝"));
    await user.click(within(rejectedFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("status=rejected");
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20&status=rejected",
        expect.objectContaining({ credentials: "include" }),
      );
    });

    // 「全部」是显式取值: URL 记 status=all, 请求不带 status。
    const allFilter = await openHeaderFilter(user, "状态");
    await user.click(within(allFilter).getByText("全部"));
    await user.click(within(allFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("status=all");
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20",
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("重置状态筛选回到默认的待审批口径, 空筛选不等于全部", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = accessRequestsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-requests", "?status=all");

    await screen.findByText("胡玉琴");
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/operations/access-requests?page=1&page_size=20",
      expect.objectContaining({ credentials: "include" }),
    );

    // antd 的「重置」只清空下拉里的选中项, 提交仍要点「确定」。
    const statusFilter = await openHeaderFilter(user, "状态");
    await user.click(within(statusFilter).getByRole("button", { name: "重置" }));
    await user.click(within(statusFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).not.toHaveTextContent("status=");
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted",
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
          data: [auditLogRow()],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers({ now: new Date("2026-09-13T12:00:00+08:00"), toFake: ["Date"] });
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("audit");

    await screen.findByText("grant.approved");

    const timeFilter = await openHeaderFilter(user, "时间");
    await user.click(within(timeFilter).getByPlaceholderText("开始日期"));
    await user.click(await screen.findByText("近7天"));
    await user.click(within(timeFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        `/console/api/v1/audit-logs?page=1&page_size=20&created_from=${encodedBound("2026-09-07", "from")}&created_to=${encodedBound("2026-09-13", "to")}`,
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      `created_from=${encodedBound("2026-09-07", "from")}`,
    );
  });

  test("展示失败原因并通过带原因确认框重试授权(FF-21)", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted") {
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
      if (url === "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted") {
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
    expect(screen.getByText("捷发-安环部")).toBeInTheDocument();
    expect(screen.queryByText("risk-user")).not.toBeInTheDocument();
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
    // 表格一律不设默认排序: 后端默认按用户姓名排, 表头不带指示器, 请求不带 ordering。
    expect(columnSortOrder("用户")).toBeNull();
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

  test("依赖健康立即检测成功后按响应刷新表格, 不清空行", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/operations/dependency-health") {
        return jsonResponse({
          data: [
            { component: "authentik", status: "healthy", summary: "正常", error_summary: "", last_checked_at: "2026-07-02T00:00:00Z" },
          ],
        });
      }
      if (url === "/console/api/v1/operations/dependency-health/checks" && init?.method === "POST") {
        return jsonResponse({
          data: [
            { component: "authentik", status: "unhealthy", summary: "调用失败", error_summary: "HTTP 500", last_checked_at: "2026-07-02T01:00:00Z" },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("dependency-health");

    expect(await screen.findByText("正常")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "立即检测" }));

    // 检测响应直接写回分区缓存: 行必须仍在, 且换成最新结果。
    expect(await screen.findByText("调用失败")).toBeVisible();
    expect(screen.getByText("authentik")).toBeVisible();
    expect(screen.queryByText("暂无运营数据")).not.toBeInTheDocument();
  });

  test("授权列表的创建时间范围由 RangePicker 承载并与 URL 往返", async () => {
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
    vi.useFakeTimers({ now: new Date("2026-09-13T12:00:00+08:00"), toFake: ["Date"] });
    const user = userEvent.setup({ delay: null });

    renderOperationsPage(
      "access-grants",
      "?created_from=2026-07-01T00%3A00%3A00&created_to=2026-07-10T23%3A59%3A59",
    );

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&created_from=2026-07-01T00%3A00%3A00&created_to=2026-07-10T23%3A59%3A59&current_only=true",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    const range = screen.getByRole("group", { name: "创建时间" });
    const inputs = within(range).getAllByRole("textbox");
    expect(inputs[0]).toHaveValue("2026-07-01");
    expect(inputs[1]).toHaveValue("2026-07-10");

    await user.click(inputs[0]);
    await user.click(await screen.findByText("本月"));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringContaining(`created_from=${encodedBound("2026-09-01", "from")}`),
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(screen.getByTestId("location-search")).toHaveTextContent(
      `created_to=${encodedBound("2026-09-30", "to")}`,
    );
  });

  test("授权列表创建时间 URL 带 +08:00 时回填同一日历日", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage(
      "access-grants",
      "?created_from=2026-09-13T00%3A00%3A00%2B08%3A00&created_to=2026-09-13T23%3A59%3A59%2B08%3A00",
    );

    const range = await screen.findByRole("group", { name: "创建时间" });
    const inputs = within(range).getAllByRole("textbox");
    expect(inputs[0]).toHaveValue("2026-09-13");
    expect(inputs[1]).toHaveValue("2026-09-13");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("created_from=2026-09-13T00%3A00%3A00%2B08%3A00"),
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("授权列表创建时间 URL 带 Z 时回填同一日历日, 再确认不跨日", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.useFakeTimers({ now: new Date("2026-09-13T12:00:00+08:00"), toFake: ["Date"] });
    const user = userEvent.setup({ delay: null });

    renderOperationsPage(
      "access-grants",
      "?created_from=2026-09-13T00%3A00%3A00Z&created_to=2026-09-13T23%3A59%3A59Z",
    );

    const range = await screen.findByRole("group", { name: "创建时间" });
    const inputs = within(range).getAllByRole("textbox");
    expect(inputs[0]).toHaveValue("2026-09-13");
    expect(inputs[1]).toHaveValue("2026-09-13");

    await user.click(inputs[0]);
    await user.click(await screen.findByText("近7天"));
    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent(
        `created_from=${encodedBound("2026-09-07", "from")}`,
      );
      expect(screen.getByTestId("location-search")).toHaveTextContent(
        `created_to=${encodedBound("2026-09-13", "to")}`,
      );
    });
    expect(within(range).getAllByRole("textbox")[0]).toHaveValue("2026-09-07");
    expect(within(range).getAllByRole("textbox")[1]).toHaveValue("2026-09-13");
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
    const emptyRange = await screen.findByRole("group", { name: "创建时间" });
    expect(emptyRange.querySelector(".ant-picker-clear")).not.toBeInTheDocument();
    unmount();

    renderOperationsPage(
      "access-grants",
      "?created_from=2026-07-01T00%3A00%3A00&created_to=2026-07-10T23%3A59%3A59",
    );

    const range = await screen.findByRole("group", { name: "创建时间" });
    const picker = range.querySelector(".ant-picker");
    expect(picker).toBeTruthy();
    fireEvent.mouseEnter(picker as HTMLElement);
    await user.click(range.querySelector(".ant-picker-clear") as HTMLElement);

    await waitFor(() => {
      expect(screen.getByTestId("location-search")).not.toHaveTextContent("created_from");
    });
    expect(screen.getByTestId("location-search")).not.toHaveTextContent("created_to");
    expect(within(range).getAllByRole("textbox")[0]).toHaveValue("");
    expect(range.querySelector(".ant-picker-clear")).not.toBeInTheDocument();
  });

  test("授权明细用户模糊搜索去抖后写入 user_query, 并与 user_id 精确筛选共存", async () => {
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

    renderOperationsPage("access-grants", "?user_id=user-a");
    const search = await screen.findByPlaceholderText("搜索姓名 / 拼音 / 用户 ID");
    expect(search).toHaveValue("");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&user_id=user-a&current_only=true",
        expect.objectContaining({ credentials: "include" }),
      );
    });

    await user.type(search, "张三");
    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("user_query");
      expect(screen.getByTestId("location-search")).toHaveTextContent("user_id=user-a");
      expect(fetchMock).toHaveBeenLastCalledWith(
        expect.stringMatching(/user_id=user-a.*user_query=|user_query=.*user_id=user-a/),
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("授权明细从 URL 回填 user_query", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/access-grants?")) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 1 } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderOperationsPage("access-grants", "?user_query=%E5%BC%A0%E4%B8%89");

    expect(await screen.findByPlaceholderText("搜索姓名 / 拼音 / 用户 ID")).toHaveValue("张三");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-grants?page=1&page_size=20&user_query=%E5%BC%A0%E4%B8%89&current_only=true",
        expect.objectContaining({ credentials: "include" }),
      );
    });
  });

  test("改其他筛选时未提交的用户搜索不会被 URL 同步冲掉", async () => {
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

    renderOperationsPage("access-grants");
    const search = await screen.findByPlaceholderText("搜索姓名 / 拼音 / 用户 ID");
    await user.type(search, "张三");
    expect(search).toHaveValue("张三");
    expect(screen.getByTestId("location-search")).not.toHaveTextContent("user_query");

    await user.click(screen.getByRole("checkbox", { name: "包含历史版本" }));

    expect(search).toHaveValue("张三");
    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("user_query");
      expect(screen.getByTestId("location-search")).toHaveTextContent("include_history=1");
    });
    expect(search).toHaveValue("张三");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringMatching(/user_query=.*current_only=false|current_only=false.*user_query=/),
        expect.objectContaining({ credentials: "include" }),
      );
    });
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

  test("待审批表头排序写入 URL 并带 ordering 请求", async () => {
    document.body.dataset.currentUserRole = "admin";
    const fetchMock = accessRequestsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderOperationsPage("access-requests");
    await screen.findByText("胡玉琴");
    expect(columnSortOrder("状态")).toBeNull();

    await sortByColumn(user, "状态");
    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("ordering=status");
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/access-requests?page=1&page_size=20&status=submitted&ordering=status",
        expect.objectContaining({ credentials: "include" }),
      );
    });
    expect(columnSortOrder("状态")).toBe("ascend");

    await sortByColumn(user, "状态");
    await waitFor(() => {
      expect(screen.getByTestId("location-search")).toHaveTextContent("ordering=-status");
      expect(columnSortOrder("状态")).toBe("descend");
    });
  });
});

/** 访问申请分区的取数桩: 只关心请求 URL, 行内容固定。 */
function accessRequestsFetchMock() {
  return vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url.startsWith("/console/api/v1/operations/access-requests?")) {
      return jsonResponse({
        data: [accessRequestRow()],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

/** 表头枚举筛选里当前选中项的文案(单选下拉)。 */
function selectedFilterOption(dropdown: HTMLElement): string {
  const selected = dropdown.querySelector(".ant-dropdown-menu-item-selected");
  return selected?.textContent?.trim() ?? "";
}

/** 审计日志行: actor_person 必填, 缺省 null 表示系统/未解析到 UserMirror。 */
function auditLogRow(overrides: Record<string, unknown> = {}) {
  return {
    actor_type: "user",
    actor_id: "admin-1",
    event_type: "grant.approved",
    target_type: "access_request",
    target_id: "req-9",
    metadata: { app_key: "crm" },
    created_at: "2026-07-02T00:00:00Z",
    actor_person: null,
    ...overrides,
  };
}

/** 访问申请行(A3: 姓名 / 应用名 / 审批人姓名随行下发)。 */
function accessRequestRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    user_id: "user-a",
    user_name: "胡玉琴",
    user_department: "捷发-安环部",
    user_account_kind: "directory",
    app_key: "crm",
    app_name: "CRM",
    app_alias: "客户管理",
    status: "submitted",
    request_type: "grant",
    approvers: [{ user_id: "manager-1", name: "张主管", account_kind: "directory" }],
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
    user_department: "捷发-安环部",
    user_account_kind: "directory",
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

/** 本地日界写入 URL / 查询串时的百分号编码。 */
function encodedBound(date: string, bound: "from" | "to"): string {
  return encodeURIComponent(formatDateRangeBound(dayjs(date), bound));
}
