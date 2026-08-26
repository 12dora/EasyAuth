import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsoleAppList } from "./ConsoleAppList";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  openHeaderFilter,
  renderWithAntd,
  sortByColumn,
} from "../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

describe("ConsoleAppList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.dataset.currentUserRole = "";
  });

  test("管理员看到快速新建和接入向导入口", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse({ data: [] })));

    renderList();

    expect(await screen.findByRole("button", { name: "快速新建" })).toBeVisible();
    expect(screen.getByRole("button", { name: "接入向导" })).toBeVisible();
  });

  test("管理员可以在列表行内启停，并在核对应用名称和 Key 后删除", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/apps?") && !init?.method) {
        return jsonResponse({
          data: [
            {
              id: 1,
              app_key: "crm",
              name: "CRM",
              owners: ["owner-a"],
              is_active: true,
              updated_at: "2026-07-01T09:00:00Z",
              capabilities: { can_delete: true, can_toggle_active: true },
            },
            {
              id: 2,
              app_key: "billing",
              name: "Billing",
              owners: ["owner-b"],
              is_active: false,
              updated_at: "2026-07-01T09:00:00Z",
              capabilities: { can_delete: true, can_toggle_active: true },
            },
          ],
        });
      }
      if (url === "/console/api/v1/apps/crm" && init?.method === "PATCH") {
        return jsonResponse({ ok: true });
      }
      if (url === "/console/api/v1/apps/billing" && init?.method === "PATCH") {
        return jsonResponse({ ok: true });
      }
      if (url === "/console/api/v1/apps/crm" && init?.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    const crmRow = await screen.findByRole("row", { name: /CRM/ });
    const billingRow = screen.getByRole("row", { name: /Billing/ });

    await user.click(within(crmRow).getByRole("button", { name: "停用" }));
    await user.click(within(billingRow).getByRole("button", { name: "启用" }));
    await user.click(within(crmRow).getByRole("button", { name: "删除" }));

    const deleteDialog = await screen.findByRole("dialog", { name: "删除 CRM" });
    expect(within(deleteDialog).getByText("应用名称: CRM; 应用 Key: crm")).toBeVisible();
    expect(findFetchCall(fetchMock, "/console/api/v1/apps/crm", "DELETE")).toBeUndefined();
    await user.click(within(deleteDialog).getByRole("button", { name: "删除" }));

    await waitFor(() => {
      expect(parseJsonBody(findFetchCall(fetchMock, "/console/api/v1/apps/crm", "PATCH")?.[1])).toEqual({ is_active: false });
      expect(parseJsonBody(findFetchCall(fetchMock, "/console/api/v1/apps/billing", "PATCH")?.[1])).toEqual({ is_active: true });
      expect(findFetchCall(fetchMock, "/console/api/v1/apps/crm", "DELETE")).toBeDefined();
    });
  });

  test("表头状态筛选映射成后端 status 查询参数并回到第 1 页", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ data: [], pagination: emptyPagination() }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await waitFor(() => expect(listRequestUrls(fetchMock)).toContain("/console/api/v1/apps?page=1&page_size=20&ordering=app_key"));

    const dropdown = await openHeaderFilter(user, "状态");
    await user.click(within(dropdown).getByText("启用"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() =>
      expect(listRequestUrls(fetchMock)).toContain("/console/api/v1/apps?page=1&page_size=20&status=active&ordering=app_key"),
    );
  });

  test("表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const page = new URLSearchParams(String(input).split("?")[1]).get("page") ?? "1";
      return jsonResponse({
        data: [
          {
            id: 1,
            app_key: `app-${page}`,
            name: `应用${page}`,
            owners: [],
            is_active: true,
            updated_at: "2026-07-01T09:00:00Z",
            capabilities: {},
          },
        ],
        pagination: { page: Number(page), page_size: 20, total_items: 40, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    // 首屏的 defaultSort 与后端默认序(app_key 升序)一致, 表头就带着指示器。
    await screen.findByText("应用1");
    expect(columnSortOrder("应用")).toBe("ascend");

    await user.click(screen.getByTitle("下一页"));
    await screen.findByText("应用2");

    await sortByColumn(user, "更新时间");
    await waitFor(() =>
      expect(lastListUrl(fetchMock)).toBe("/console/api/v1/apps?page=1&page_size=20&ordering=updated_at"),
    );
    expect(columnSortOrder("更新时间")).toBe("ascend");
    expect(columnSortOrder("应用")).toBeNull();

    await sortByColumn(user, "更新时间");
    await waitFor(() =>
      expect(lastListUrl(fetchMock)).toBe("/console/api/v1/apps?page=1&page_size=20&ordering=-updated_at"),
    );
    expect(columnSortOrder("更新时间")).toBe("descend");
  });

  test("表头筛选是服务端筛选: 确定后图标保持高亮, 当前页不再被客户端筛一遍", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    // 后端按 status=active 返回的这一页里混着一行 is_active: false —— 翻页时
    // placeholderData 留下的上一页就是这样。客户端再筛一遍会把它静默丢掉。
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        data: [
          {
            id: 1,
            app_key: "crm",
            name: "CRM",
            owners: ["owner-a"],
            is_active: true,
            updated_at: "2026-07-01T09:00:00Z",
            capabilities: {},
          },
          {
            id: 2,
            app_key: "billing",
            name: "Billing",
            owners: ["owner-b"],
            is_active: false,
            updated_at: "2026-07-01T09:00:00Z",
            capabilities: {},
          },
        ],
        pagination: { page: 1, page_size: 20, total_items: 2, total_pages: 1 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await screen.findByText("CRM");
    const dropdown = await openHeaderFilter(user, "状态");
    await user.click(within(dropdown).getByText("启用"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() =>
      expect(listRequestUrls(fetchMock)).toContain("/console/api/v1/apps?page=1&page_size=20&status=active&ordering=app_key"),
    );
    // Billing 是「停用」, 与生效中的筛选值不符, 但它是后端这一页返回的行, 必须照常展示。
    expect(await screen.findByText("Billing")).toBeVisible();
    expect(screen.getByText("CRM")).toBeVisible();
    // 受控 filteredValue: 表头图标与实际请求参数一致。
    await waitFor(() => expect(statusFilterTrigger()).toHaveClass("active"));
  });

  test("创建成功后跳转到新应用工作区", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/apps?") && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/apps" && init?.method === "POST") {
        return jsonResponse({ app: { id: 2, app_key: "billing", name: "Billing" } }, 201);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderList();

    await user.click(await screen.findByRole("button", { name: "快速新建" }));
    await user.type(screen.getByLabelText("app_key"), "billing");
    await user.type(screen.getByLabelText("名称"), "Billing");
    await user.type(screen.getByLabelText("描述"), "Billing app");
    await user.type(screen.getByLabelText("Owner 用户 ID"), "owner-a, owner-b");
    await user.type(screen.getByLabelText("Developer 用户 ID"), "dev-a");
    await user.click(screen.getByRole("button", { name: "创建" }));

    await waitFor(() => {
      const postCall = findFetchCall(fetchMock, "/console/api/v1/apps", "POST");
      expect(parseJsonBody(postCall?.[1])).toEqual({
        app_key: "billing",
        name: "Billing",
        description: "Billing app",
        owner_user_ids: ["owner-a", "owner-b"],
        developer_user_ids: ["dev-a"],
      });
    });
    expect(await screen.findByTestId("location")).toHaveTextContent("/console/apps/billing");
  });
});

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
      <MemoryRouter initialEntries={["/console"]}>
        <Routes>
          <Route path="/console" element={<ConsoleAppList />} />
          <Route path="/console/apps/:appKey" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function listRequestUrls(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.startsWith("/console/api/v1/apps?"));
}

function lastListUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return listRequestUrls(fetchMock).at(-1);
}

function emptyPagination() {
  return { page: 1, page_size: 20, total_items: 0, total_pages: 1 };
}

function findFetchCall(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, url: string, method: string) {
  return fetchMock.mock.calls.find(([input, init]) => String(input) === url && init?.method === method);
}

function parseJsonBody(init: RequestInit | undefined) {
  return JSON.parse(String(init?.body));
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

