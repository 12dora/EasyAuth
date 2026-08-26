import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { HandoverTaskList } from "./HandoverTaskList";
import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "../../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

describe("HandoverTaskList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("按服务端总数展示分页并请求下一页", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      const page = url.includes("page=2") ? 2 : 1;
      return jsonResponse({
        data: [
          {
            id: page,
            kind: "offboard",
            status: "pending",
            allowed_actions: [],
            subject: {
              user_id: `u-${page}`,
              name: `员工${page}`,
              email: "",
              department: "",
              status: "active",
            },
            reason: "",
            created_by: "admin",
            created_at: "2026-07-10T00:00:00Z",
            updated_at: "2026-07-10T00:00:00Z",
          },
        ],
        pagination: { page, page_size: 10, total_items: 11, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    expect(await screen.findByText("员工1")).toBeVisible();
    expect(screen.getByText("第 1-10 条 / 共 11 条")).toBeVisible();
    await user.click(screen.getByTitle("下一页"));

    expect(await screen.findByText("员工2")).toBeVisible();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("page=2&page_size=10"),
        expect.any(Object),
      ),
    );
    expect(screen.getByText("第 11-11 条 / 共 11 条")).toBeVisible();
  });

  test("四个过滤条件都在表头, 选中后映射成后端查询参数", async () => {
    const rows = [taskRow(1, "人员待处理", "pending", [])];
    const fetchMock = vi.fn<typeof fetch>(async (input) =>
      jsonResponse({
        data: String(input).includes("status=cancelled") ? [] : rows,
        pagination: { page: 1, page_size: 10, total_items: 1, total_pages: 1 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("人员待处理");
    // 表格外的四个过滤下拉已经删除, 全部改由表头承载。
    expect(screen.queryByLabelText("交接状态")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("交接类型")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("负责人状态")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("是否阻塞")).not.toBeInTheDocument();

    const dropdown = await openHeaderFilter(user, "状态");
    await user.click(within(dropdown).getByText("已取消"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/lifecycle/handover-tasks?page=1&page_size=10&status=cancelled",
        expect.any(Object),
      ),
    );
  });

  test("删除动作只按后端 allowed_actions 展示并执行", async () => {
    const rows = [
      taskRow(1, "人员待处理", "pending", []),
      taskRow(2, "人员处理中", "in_progress", []),
      taskRow(3, "人员已完成", "completed", []),
      taskRow(4, "人员已取消", "cancelled", ["delete"]),
    ];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/lifecycle/handover-tasks?") && !init?.method) {
        return jsonResponse({
          data: rows,
          pagination: { page: 1, page_size: 10, total_items: rows.length, total_pages: 1 },
        });
      }
      if (url === "/console/api/v1/lifecycle/handover-tasks/4" && init?.method === "DELETE") {
        return jsonResponse({ deleted: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("人员已取消");
    expect(rowFor("人员待处理")).not.toHaveTextContent("删除");
    expect(rowFor("人员处理中")).not.toHaveTextContent("删除");
    expect(rowFor("人员已完成")).not.toHaveTextContent("删除");
    await user.click(within(rowFor("人员已取消")).getByRole("button", { name: "删除" }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/lifecycle/handover-tasks/4",
        expect.objectContaining({ method: "DELETE" }),
      );
    });
  });
});

function taskRow(id: number, name: string, status: string, allowedActions: string[]) {
  return {
    id,
    kind: "offboard",
    status,
    allowed_actions: allowedActions,
    subject: {
      user_id: `u-${id}`,
      name,
      email: "",
      department: "",
      status: "active",
    },
    reason: "",
    created_by: "admin",
    created_at: "2026-07-10T00:00:00Z",
    updated_at: "2026-07-10T00:00:00Z",
  };
}

function rowFor(name: string) {
  const row = screen.getByText(name).closest("tr");
  expect(row).not.toBeNull();
  return row as HTMLTableRowElement;
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
      <MemoryRouter>
        <HandoverTaskList />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

