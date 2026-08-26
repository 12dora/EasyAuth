import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { OverviewTab } from "./OverviewTab";
import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "../../../../components/antd/testing";

// antd Table 每次筛选都要重建整棵表格, jsdom 下比自研原语慢, 放宽本文件超时。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

afterEach(() => {
  vi.unstubAllGlobals();
});

test("概览显示权威授权组数量", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/configuration-status")) {
        return jsonResponse({ status: "ready", data: [] });
      }
      if (url.endsWith("/memberships")) {
        return jsonResponse({ data: [] });
      }
      return jsonResponse({}, 404);
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <OverviewTab
        appKey="demo"
        app={{
          id: 1,
          app_key: "demo",
          name: "Demo",
          authorization_group_count: 7,
        }}
      />
    </QueryClientProvider>,
  );

  const metric = screen.getByText("授权组").parentElement;
  expect(metric).not.toBeNull();
  expect(within(metric as HTMLElement).getByText("7")).toBeInTheDocument();
});

test("使用真实成员序列化形状按 membership ID 停用成员", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/configuration-status")) {
      return jsonResponse({ status: "ready", data: [] });
    }
    if (url.endsWith("/memberships") && !init?.method) {
      return jsonResponse({
        data: [{ id: 42, user_id: "member-42", role: "developer", is_active: true }],
      });
    }
    if (url.endsWith("/memberships/42") && init?.method === "PATCH") {
      return jsonResponse({
        membership: { id: 42, user_id: "member-42", role: "developer", is_active: false },
      });
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <OverviewTab
        appKey="demo"
        app={{ id: 1, app_key: "demo", name: "Demo", capabilities: { can_manage_memberships: true } }}
      />
    </QueryClientProvider>,
  );

  await screen.findByText("member-42");
  const membersPanel = screen.getByRole("heading", { name: "成员" }).closest("section");
  expect(membersPanel).not.toBeNull();
  fireEvent.click(within(membersPanel as HTMLElement).getByRole("button", { name: "停用" }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/apps/demo/memberships/42",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ is_active: false }) }),
    );
  });
});

test("成员表头按角色筛选并保留 AppTable 分页", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/configuration-status")) {
        return jsonResponse({ status: "ready", data: [] });
      }
      if (url.endsWith("/memberships")) {
        return jsonResponse({
          data: [
            { id: 11, user_id: "owner-a", role: "owner", is_active: true },
            { id: 22, user_id: "dev-a", role: "developer", is_active: true },
          ],
        });
      }
      return jsonResponse({}, 404);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // antd 表格每次筛选都要整表重渲染, user-event 默认的事件间隔会让本用例逼近超时。
  const user = userEvent.setup({ delay: null });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <OverviewTab appKey="demo" app={{ id: 1, app_key: "demo", name: "Demo" }} />
    </QueryClientProvider>,
  );

  await screen.findByText("owner-a");
  const membersPanel = screen.getByRole("heading", { name: "成员" }).closest("section") as HTMLElement;
  expect(membershipUserIds(membersPanel)).toEqual(["owner-a", "dev-a"]);
  expect(membersPanel.querySelector("ul.ant-pagination .ant-pagination-total-text")).not.toBeNull();

  const roleDropdown = await openHeaderFilter(user, membersPanel, "角色");
  await user.click(within(roleDropdown).getByText("开发者"));
  await user.click(within(roleDropdown).getByRole("button", { name: "确定" }));

  await waitFor(() => expect(membershipUserIds(membersPanel)).toEqual(["dev-a"]));
});

/** 打开指定表头的筛选下拉, 返回当前展开的那个下拉面板。 */

function membershipUserIds(scope: HTMLElement): string[] {
  return [...scope.querySelectorAll(".ant-table-tbody tr.ant-table-row")].map(
    (row) => row.querySelector("td")?.textContent ?? "",
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
