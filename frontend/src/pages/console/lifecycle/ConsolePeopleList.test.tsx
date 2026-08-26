import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsolePeopleList } from "./ConsolePeopleList";
import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "../../../components/antd/testing";

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
    },
    {
      user_id: "u-2",
      name: "李四",
      email: "lisi@example.com",
      department: "客服部",
      status: "departed",
      open_handover_task_id: 12,
      open_handover_kind: "offboard",
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

