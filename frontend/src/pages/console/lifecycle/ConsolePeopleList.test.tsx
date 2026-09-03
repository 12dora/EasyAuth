import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsolePeopleList } from "./ConsolePeopleList";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  openHeaderFilter,
  renderWithAntd,
  sortByColumn,
} from "../../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const PEOPLE_PAYLOAD = {
  data: [
    {
      user_id: "u-1",
      name: "张三",
      email: "zhangsan@example.com",
      department: "销售部",
      status: "active",
      open_handover_task_id: null,
      open_handover_kind: "",
      is_console_admin: false,
    },
    {
      user_id: "u-2",
      name: "李四",
      email: "lisi@example.com",
      department: "客服部",
      status: "departed",
      open_handover_task_id: 12,
      open_handover_kind: "offboard",
      is_console_admin: true,
    },
  ],
  pagination: { page: 1, page_size: 20, total_items: 2, total_pages: 1 },
};

describe("ConsolePeopleList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("人员列表展示状态徽标与行操作", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url.startsWith("/console/api/v1/users?page=")) {
          return jsonResponse(PEOPLE_PAYLOAD);
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );

    renderList();

    expect(await screen.findByText("张三")).toBeVisible();
    const table = within(screen.getByRole("table"));
    expect(table.getByText("在职")).toBeVisible();
    expect(table.getByText("李四")).toBeVisible();
    expect(table.getByText("已离职")).toBeVisible();
    // 已离职且有进行中交接单 → 去交接; 在职 → 发起离职交接 / 发起转岗。
    expect(screen.getByRole("link", { name: "去交接" })).toHaveAttribute("href", "/console/lifecycle/handover-tasks/12");
    expect(screen.getByRole("button", { name: "离职交接" })).toBeVisible();
    expect(screen.getByRole("button", { name: "转岗" })).toBeVisible();
    // 管理员身份与在职状态无关, 因此「权限」入口每行都有(含已离职行)。
    expect(within(personRow("张三")).getByRole("button", { name: "权限" })).toBeVisible();
    expect(within(personRow("李四")).getByRole("button", { name: "权限" })).toBeVisible();
    // 管理员列: 李四是管理员 → 徽章; 张三不是 → statusColumn 的空值占位。
    expect(within(personRow("李四")).getByText("是")).toBeVisible();
    expect(within(personRow("张三")).queryByText("是")).not.toBeInTheDocument();
  });

  test("权限弹窗: 勾选管理员后 PUT console-admin, 成功即关闭并重新拉列表", async () => {
    // 保存成功后后端返回的那一页: 张三已经是管理员。列表刷新是唯一真相, 前端不就地改写。
    const updatedPayload = {
      ...PEOPLE_PAYLOAD,
      data: [{ ...PEOPLE_PAYLOAD.data[0], is_console_admin: true }, PEOPLE_PAYLOAD.data[1]],
    };
    let saved = false;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/users?page=")) {
        return jsonResponse(saved ? updatedPayload : PEOPLE_PAYLOAD);
      }
      if (url === "/console/api/v1/users/u-1/console-admin" && init?.method === "PUT") {
        saved = true;
        return jsonResponse({ user: updatedPayload.data[0] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("张三");
    await user.click(within(personRow("张三")).getByRole("button", { name: "权限" }));

    const dialog = await screen.findByRole("dialog");
    const checkbox = within(dialog).getByRole("checkbox", { name: "设为管理员，可进入管理后台" });
    expect(checkbox).not.toBeChecked();
    await user.click(checkbox);
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        ([callInput, callInit]) =>
          String(callInput) === "/console/api/v1/users/u-1/console-admin" && callInit?.method === "PUT",
      );
      expect(JSON.parse(String(putCall?.[1]?.body))).toEqual({ is_console_admin: true });
    });
    // 成功后弹窗关闭, 且列表被重新拉取(新的一页里张三带上了管理员徽章)。
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(within(personRow("张三")).getByText("是")).toBeVisible());
  });

  test("权限弹窗: 后端拒绝时原样展示后端文案, 弹窗保持打开", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/users?page=")) {
        return jsonResponse(PEOPLE_PAYLOAD);
      }
      if (url === "/console/api/v1/users/u-2/console-admin" && init?.method === "PUT") {
        return jsonResponse(
          { error: { code: "CONSOLE_ADMIN_SELF_REVOKE", message: "不能取消自己的管理员权限。" } },
          422,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("李四");
    await user.click(within(personRow("李四")).getByRole("button", { name: "权限" }));

    const dialog = await screen.findByRole("dialog");
    // 李四已是管理员, 弹窗初值就是勾选态; 取消勾选后保存。
    const checkbox = within(dialog).getByRole("checkbox", { name: "设为管理员，可进入管理后台" });
    expect(checkbox).toBeChecked();
    await user.click(checkbox);
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    expect(await within(dialog).findByText("不能取消自己的管理员权限。")).toBeVisible();
    expect(within(dialog).getByText("权限保存失败")).toBeVisible();
    expect(screen.getByRole("dialog")).toBeVisible();
    // 后端拒绝后列表不得出现「已生效」的假象: PUT 之后没有额外的列表请求。
    expect(fetchMock.mock.calls.filter(([callInput]) => String(callInput).startsWith("/console/api/v1/users?")).length).toBe(1);
  });

  test("在职状态迁到表头筛选, 选中后映射成 status 查询参数", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/users?page=")) {
        return jsonResponse(PEOPLE_PAYLOAD);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("张三");
    // 工具栏只剩跨列搜索, 状态下拉已经不在表格外。
    expect(screen.getByLabelText("搜索姓名 / 邮箱 / 用户 ID")).toBeVisible();
    expect(screen.queryByLabelText("在职状态")).not.toBeInTheDocument();

    const dropdown = await openHeaderFilter(user, "状态");
    await user.click(within(dropdown).getByText("在职"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/console/api/v1/users?page=1&page_size=20&status=active", expect.any(Object)),
    );
  });

  test("状态筛选是服务端筛选: 确定后图标保持高亮, 当前页不再被客户端筛一遍", async () => {
    // 后端按 status=active 返回的这一页里, 只要有一行的状态和筛选值对不上
    // (翻页时 placeholderData 留下的上一页就是这样), 客户端再筛一遍就会把它筛掉。
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/users?page=")) {
        return jsonResponse(PEOPLE_PAYLOAD);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("张三");
    const dropdown = await openHeaderFilter(user, "状态");
    await user.click(within(dropdown).getByText("在职"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/console/api/v1/users?page=1&page_size=20&status=active", expect.any(Object)),
    );
    // 李四是「已离职」, 与生效中的筛选值不符, 但它是后端这一页返回的行, 必须照常展示。
    expect(await screen.findByText("李四")).toBeVisible();
    expect(screen.getByText("张三")).toBeVisible();
    // 受控 filteredValue: 表头图标与实际请求参数一致。
    await waitFor(() => expect(statusFilterTrigger()).toHaveClass("active"));
  });

  test("表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (!url.startsWith("/console/api/v1/users?page=")) {
        throw new Error(`Unexpected fetch: ${url}`);
      }
      const page = new URLSearchParams(url.split("?")[1]).get("page") ?? "1";
      return jsonResponse({
        data: [
          {
            user_id: `u-${page}`,
            name: `员工${page}`,
            email: `u${page}@example.com`,
            department: "销售部",
            status: "active",
            open_handover_task_id: null,
            open_handover_kind: "",
            is_console_admin: false,
          },
        ],
        pagination: { page: Number(page), page_size: 20, total_items: 40, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    // 表格不设默认排序: 首屏不带 ordering, 表头也没有指示器。
    await screen.findByText("员工1");
    expect(columnSortOrder("姓名")).toBeNull();

    await user.click(screen.getByTitle("下一页"));
    await screen.findByText("员工2");

    await sortByColumn(user, "部门");
    await waitFor(() =>
      expect(lastListUrl(fetchMock)).toBe("/console/api/v1/users?page=1&page_size=20&ordering=department"),
    );
    expect(columnSortOrder("部门")).toBe("ascend");
    expect(columnSortOrder("姓名")).toBeNull();

    await sortByColumn(user, "部门");
    await waitFor(() =>
      expect(lastListUrl(fetchMock)).toBe("/console/api/v1/users?page=1&page_size=20&ordering=-department"),
    );
    expect(columnSortOrder("部门")).toBe("descend");
  });

  test("发起离职交接: 确认对话框提交后建单并跳转交接单详情", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/users?page=")) {
        return jsonResponse(PEOPLE_PAYLOAD);
      }
      if (url === "/console/api/v1/lifecycle/handover-tasks" && init?.method === "POST") {
        return jsonResponse(
          {
            handover_task: {
              id: 9,
              kind: "offboard",
              status: "pending",
              subject: PEOPLE_PAYLOAD.data[0],
              reason: "工作交接",
              created_by: "admin",
              created_at: "2026-07-06T09:00:00Z",
              updated_at: "2026-07-06T09:00:00Z",
              app_actions: [],
              team_items: [],
              transfer_plan: null,
            },
          },
          201,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await user.click(await screen.findByRole("button", { name: "离职交接" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    await user.type(screen.getByLabelText("备注原因"), "工作交接");
    await user.click(screen.getByRole("button", { name: "创建交接单" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/console/api/v1/lifecycle/handover-tasks" && init?.method === "POST",
      );
      expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({
        kind: "offboard",
        user_id: "u-1",
        reason: "工作交接",
      });
    });
    expect(await screen.findByTestId("location")).toHaveTextContent("/console/lifecycle/handover-tasks/9");
  });
});

function lastListUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/console/api/v1/users?"))
    .at(-1);
}

/** 按姓名定位表格行, 用来把断言限定在某一行的单元格上。 */
function personRow(name: string): HTMLElement {
  const row = screen.getByText(name).closest("tr");
  expect(row).not.toBeNull();
  return row as HTMLElement;
}

/** 「状态」列表头上的筛选图标。 */
function statusFilterTrigger(): HTMLElement {
  const header = [...document.querySelectorAll("th.ant-table-cell")].find((cell) =>
    (cell.textContent ?? "").trim().startsWith("状态"),
  );
  expect(header).toBeDefined();
  return (header as HTMLElement).querySelector(".ant-table-filter-trigger") as HTMLElement;
}

function renderList() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/people"]}>
        <Routes>
          <Route path="/console/people" element={<ConsolePeopleList />} />
          <Route path="/console/lifecycle/handover-tasks/:taskId" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

