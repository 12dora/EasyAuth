import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsoleTeamList } from "./ConsoleTeamList";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  renderWithAntd,
  sortByColumn,
} from "../../components/antd/testing";

// antd Table 在 jsdom 里每次翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

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

  test("按服务端总数分页并请求下一页", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      const page = url.includes("page=2") ? 2 : 1;
      return jsonResponse({
        data: [
          {
            id: page,
            name: `团队${page}`,
            description: "",
            is_active: true,
            leaders: [],
            member_count: 0,
            created_at: "2026-07-01T09:00:00Z",
            updated_at: "2026-07-01T09:00:00Z",
          },
        ],
        pagination: { page, page_size: 10, total_items: 11, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    expect(await screen.findByText("团队1")).toBeVisible();
    expect(screen.getByText("第 1-10 条 / 共 11 条")).toBeVisible();

    await user.click(screen.getByTitle("2"));

    expect(await screen.findByText("团队2")).toBeVisible();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/console/api/v1/teams?page=2&page_size=10", expect.any(Object)),
    );
  });

  test("表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const page = new URLSearchParams(String(input).split("?")[1]).get("page") ?? "1";
      return jsonResponse({
        data: [
          {
            id: Number(page),
            name: `团队${page}`,
            description: "",
            is_active: true,
            leaders: [],
            member_count: 0,
            created_at: "2026-07-01T09:00:00Z",
            updated_at: "2026-07-01T09:00:00Z",
          },
        ],
        pagination: { page: Number(page), page_size: 10, total_items: 11, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    // 表格不设默认排序: 首屏不带 ordering, 表头也没有指示器。
    await screen.findByText("团队1");
    expect(columnSortOrder("团队名")).toBeNull();

    await user.click(screen.getByTitle("2"));
    await screen.findByText("团队2");

    await sortByColumn(user, "成员数");
    await waitFor(() =>
      expect(lastListUrl(fetchMock)).toBe("/console/api/v1/teams?page=1&page_size=10&ordering=member_count"),
    );
    expect(columnSortOrder("成员数")).toBe("ascend");
    expect(columnSortOrder("团队名")).toBeNull();

    await sortByColumn(user, "成员数");
    await waitFor(() =>
      expect(lastListUrl(fetchMock)).toBe("/console/api/v1/teams?page=1&page_size=10&ordering=-member_count"),
    );
    expect(columnSortOrder("成员数")).toBe("descend");
  });

  test("新建团队成功后跳转到团队详情", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/teams?") && !init?.method) {
        return jsonResponse({ data: [], pagination: { page: 1, page_size: 10, total_items: 0, total_pages: 1 } });
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

  renderWithAntd(
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

function lastListUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/console/api/v1/teams?"))
    .at(-1);
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
