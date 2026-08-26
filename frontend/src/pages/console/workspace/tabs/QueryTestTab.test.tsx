import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { AppConfigProvider } from "../../../../components/antd/AppConfigProvider";
import { QueryTestTab } from "./QueryTestTab";

// antd Table 在 jsdom 里每次筛选/排序/翻页都要重建整棵表格, 比自研原语慢得多,
// 整套用例并行跑时默认 5s 不够; 这里只放宽本文件的用例超时。
vi.setConfig({ testTimeout: 20000 });

describe("QueryTestTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("展示 MANAGED_USERS resolved 明细且普通 grant 不受影响", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/permission-query-tests" && init?.method === "POST") {
        return jsonResponse({
          app_key: "demo",
          user_id: "alice",
          allowed: true,
          source: "live",
          snapshot_version: "snap-20260701",
          groups: [],
          grants: [
            {
              permission: "invoice.read",
              scope: "SELF",
              source_type: "direct",
              source_key: "grant-1",
              snapshot_version: "snap-20260701",
            },
            {
              permission: "expense.approve",
              scope: "MANAGED_USERS",
              source_type: "group",
              source_key: "manager",
              snapshot_version: "snap-20260701",
              resolved: {
                user_ids: ["bob", "carol"],
                resolver: "authentik",
                resolved_at: "2026-06-05T10:20:30Z",
              },
            },
            {
              permission: "expense.audit",
              scope: "MANAGED_USERS",
              source_type: "group",
              source_key: "auditor",
              snapshot_version: "snap-20260701",
              resolved: {
                user_ids: [],
                resolver: "authentik",
                resolved_at: "2026-06-05T11:00:00Z",
              },
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<QueryTestTab appKey="demo" />);

    await user.type(screen.getByLabelText("用户 ID"), "alice");
    await user.type(screen.getByLabelText("Bearer token"), "secret-bearer-token");
    await user.click(screen.getByRole("button", { name: "执行联调" }));

    expect(await screen.findByRole("columnheader", { name: "Resolved 用户数" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Resolver" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Resolved at" })).toBeInTheDocument();

    const regularRow = screen.getByText("invoice.read").closest("tr");
    expect(regularRow).not.toBeNull();
    expect(within(regularRow as HTMLTableRowElement).getAllByText("-").length).toBeGreaterThanOrEqual(3);

    const resolvedRow = screen.getByText("expense.approve").closest("tr");
    expect(resolvedRow).not.toBeNull();
    expect(within(resolvedRow as HTMLTableRowElement).getByText("2")).toBeInTheDocument();
    expect(within(resolvedRow as HTMLTableRowElement).getByText("authentik")).toBeInTheDocument();
    expect(within(resolvedRow as HTMLTableRowElement).getByText("2026-06-05T10:20:30Z")).toBeInTheDocument();

    const emptyResolvedRow = screen.getByText("expense.audit").closest("tr");
    expect(emptyResolvedRow).not.toBeNull();
    expect(within(emptyResolvedRow as HTMLTableRowElement).getByText("0")).toBeInTheDocument();

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/apps/demo/permission-query-tests",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });
  test("授权明细用表头筛选按权限过滤结果", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/permission-query-tests" && init?.method === "POST") {
        return jsonResponse({
          app_key: "demo",
          user_id: "alice",
          allowed: true,
          source: "live",
          snapshot_version: "snap-20260701",
          groups: [],
          grants: [
            { permission: "invoice.read", scope: "SELF", source_type: "direct", source_key: "grant-1" },
            { permission: "expense.approve", scope: "TEAM", source_type: "group", source_key: "manager" },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<QueryTestTab appKey="demo" />);

    await user.type(screen.getByLabelText("用户 ID"), "alice");
    await user.type(screen.getByLabelText("Bearer token"), "secret-bearer-token");
    await user.click(screen.getByRole("button", { name: "执行联调" }));

    expect(await screen.findByText("invoice.read")).toBeVisible();
    const grantsTable = screen.getByText("expense.approve").closest("table") as HTMLElement;

    await user.click(grantsTable.querySelector(".ant-table-filter-trigger") as HTMLElement);
    await user.type(await screen.findByLabelText("筛选关键字"), "expense");
    await user.click(screen.getByRole("button", { name: "确定" }));

    await waitFor(() => expect(screen.queryByText("invoice.read")).not.toBeInTheDocument());
    expect(screen.getByText("expense.approve")).toBeVisible();
  });
});

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <AppConfigProvider>{ui}</AppConfigProvider>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
