import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
