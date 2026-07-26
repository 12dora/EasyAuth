import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { HandoverTaskList } from "./HandoverTaskList";

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
    expect(screen.getByText("第 1-1 条 / 共 11 条")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("员工2")).toBeVisible();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("page=2&page_size=10"),
        expect.any(Object),
      ),
    );
    expect(screen.getByText("第 11-11 条 / 共 11 条")).toBeVisible();
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
  render(
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
