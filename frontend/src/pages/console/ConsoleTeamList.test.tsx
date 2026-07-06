import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsoleTeamList } from "./ConsoleTeamList";

describe("ConsoleTeamList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("团队列表展示团队名、负责人、成员数、状态和创建时间", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({
          data: [
            {
              id: 1,
              name: "华东销售组",
              description: "华东区销售团队",
              is_active: true,
              leaders: [
                { user_id: "u-1", name: "张三" },
                { user_id: "u-2", name: "李四" },
              ],
              member_count: 8,
              created_at: "2026-07-01T09:00:00Z",
              updated_at: "2026-07-01T09:00:00Z",
            },
            {
              id: 2,
              name: "客服组",
              description: "",
              is_active: false,
              leaders: [],
              member_count: 0,
              created_at: "2026-06-01T09:00:00Z",
              updated_at: "2026-06-01T09:00:00Z",
            },
          ],
        }),
      ),
    );

    renderList();

    expect(await screen.findByText("华东销售组")).toBeVisible();
    expect(screen.getByText("张三, 李四")).toBeVisible();
    expect(screen.getByText("8")).toBeVisible();
    expect(screen.getByText("启用")).toBeVisible();
    expect(screen.getByText("客服组")).toBeVisible();
    expect(screen.getByText("—")).toBeVisible();
    expect(screen.getByText("停用")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "查看" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "新建团队" })).toBeVisible();
  });

  test("新建团队成功后跳转到团队详情", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/teams" && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/teams" && init?.method === "POST") {
        return jsonResponse(
          { team: { id: 7, name: "新团队", description: "描述", is_active: true, leaders: [], member_count: 0, members: [] } },
          201,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await user.click(await screen.findByRole("button", { name: "新建团队" }));
    await user.type(screen.getByLabelText("名称"), "新团队");
    await user.type(screen.getByLabelText("描述"), "描述");
    await user.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => {
      const postCall = fetchMock.mock.calls.find(([input, init]) => String(input) === "/console/api/v1/teams" && init?.method === "POST");
      expect(JSON.parse(String(postCall?.[1]?.body))).toEqual({ name: "新团队", description: "描述" });
    });
    expect(await screen.findByTestId("location")).toHaveTextContent("/console/teams/7");
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
      <MemoryRouter initialEntries={["/console/teams"]}>
        <Routes>
          <Route path="/console/teams" element={<ConsoleTeamList />} />
          <Route path="/console/teams/:teamId" element={<LocationProbe />} />
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
