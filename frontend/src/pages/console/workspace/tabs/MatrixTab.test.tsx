import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { MatrixTab } from "./MatrixTab";

describe("MatrixTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("展示并保存 MANAGED_USERS grant 的管理范围策略", async () => {
    const authorizationGroupsPayload = {
      items: [
        {
          id: 10,
          key: "manager",
          kind: "role",
          name: "主管",
          description: "管理范围角色",
          requestable: true,
          is_active: true,
          grants: [
            {
              permission: "order.read",
              scope: "MANAGED_USERS",
              is_active: true,
              managed_scope_policy: {
                mode: "inherit",
                resolver: null,
                enabled: true,
              },
              effective_managed_scope_policy: {
                resolver: "dingtalk_manager_chain",
                source: "app_default",
                inherited_from: "app_default",
                health_status: "healthy",
              },
            },
            {
              permission: "order.export",
              scope: "SELF",
              is_active: true,
            },
          ],
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/authorization-groups" && !init?.method) {
        return jsonResponse(authorizationGroupsPayload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({
          items: [
            { id: 20, key: "order.read", name: "订单读取", supported_scopes: ["MANAGED_USERS"] },
            { id: 21, key: "order.export", name: "订单导出", supported_scopes: ["SELF"] },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({
          items: [
            { key: "MANAGED_USERS", name: "被管理人员", is_active: true, display_order: 1 },
            { key: "SELF", name: "本人", is_active: true, display_order: 2 },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/authorization-groups/manager" && init?.method === "PATCH") {
        return jsonResponse(authorizationGroupsPayload);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<MatrixTab appKey="demo" />);

    await screen.findByRole("heading", { name: "授权组管理" });
    await screen.findByText("主管");
    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑授权组" });

    expect(within(dialog).getByRole("columnheader", { name: "管理范围计算方式" })).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "有效策略" })).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "继承来源" })).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "健康状态" })).toBeInTheDocument();

    const managedRow = within(dialog).getByText("order.read / MANAGED_USERS").closest("tr");
    expect(managedRow).not.toBeNull();
    expect(within(managedRow as HTMLTableRowElement).getByLabelText("order.read / MANAGED_USERS 管理范围计算方式")).toHaveValue("inherit");
    expect(within(managedRow as HTMLTableRowElement).getAllByText("按钉钉主管关系").length).toBeGreaterThan(0);
    expect(within(managedRow as HTMLTableRowElement).getByText("应用默认")).toBeInTheDocument();
    expect(within(managedRow as HTMLTableRowElement).getByText("健康")).toBeInTheDocument();

    const regularRow = within(dialog).getByText("order.export / SELF").closest("tr");
    expect(regularRow).not.toBeNull();
    expect(within(regularRow as HTMLTableRowElement).queryByLabelText("order.export / SELF 管理范围计算方式")).not.toBeInTheDocument();

    await user.selectOptions(
      within(managedRow as HTMLTableRowElement).getByLabelText("order.read / MANAGED_USERS 管理范围计算方式"),
      "disabled",
    );
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/authorization-groups/manager", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        key: "manager",
        kind: "role",
        name: "主管",
        description: "管理范围角色",
        requestable: true,
        is_active: true,
        grants: [
          {
            permission: "order.read",
            scope: "MANAGED_USERS",
            is_active: true,
            managed_scope_policy: {
              mode: "disabled",
              resolver: "disabled",
              enabled: true,
            },
          },
          {
            permission: "order.export",
            scope: "SELF",
            is_active: true,
          },
        ],
      });
    });
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

  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function findFetchCall(fetchMock: ReturnType<typeof vi.fn>, url: string, method: string) {
  return fetchMock.mock.calls.find((call) => String(call[0]) === url && call[1]?.method === method);
}

function parseJsonBody(init?: RequestInit) {
  if (typeof init?.body !== "string") {
    return undefined;
  }
  return JSON.parse(init.body);
}
