import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";

import { PortalPage } from "./PortalPage";

function renderPortalPage(initialEntry = "/portal/request") {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/portal/request" element={<PortalPage />} />
          <Route path="/portal" element={<PortalPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortalPage access request form", () => {
  test("未选择角色或直接权限时不能提交申请", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          roles: [],
          permission_groups: [],
          ungrouped_permissions: [],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getAllByRole("combobox")[0], "crm");
      await user.type(screen.getByRole("textbox"), "需要申请权限");

      expect(screen.getByRole("button", { name: "提交申请" })).toBeDisabled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("限时授权未填写过期时间时不能提交申请", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          roles: [{ id: 11, app_key: "crm", key: "reader", name: "只读角色", requestable: true, requires_approval: true }],
          permission_groups: [],
          ungrouped_permissions: [],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getAllByRole("combobox")[0], "crm");
      await user.selectOptions(screen.getAllByRole("combobox")[1], "reader");
      await user.type(screen.getByRole("textbox"), "临时处理跨部门工单");
      await user.selectOptions(screen.getAllByRole("combobox")[2], "timed");

      const submitButton = screen.getByRole("button", { name: "提交申请" });
      expect(submitButton).toBeDisabled();

      await user.type(screen.getByLabelText("过期时间"), "2026-07-01T10:30");

      expect(submitButton).toBeEnabled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("按权限树展开并勾选直接权限后提交 permission_keys", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          roles: [{ id: 11, app_key: "crm", key: "reader", name: "只读角色", requestable: true, requires_approval: true }],
          permission_groups: [
            {
              id: 1,
              app_key: "crm",
              type: "group",
              key: "orders",
              name: "订单",
              permissions: [{ id: 101, app_key: "crm", key: "orders.read", name: "查看订单" }],
              children: [
                {
                  id: 2,
                  app_key: "crm",
                  type: "group",
                  key: "orders.refund",
                  name: "退款",
                  permissions: [{ id: 102, app_key: "crm", key: "orders.refund.approve", name: "审批退款" }],
                },
              ],
            },
          ],
          ungrouped_permissions: [{ id: 103, app_key: "crm", key: "dashboard.view", name: "查看看板" }],
        });
      }
      if (url === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        return jsonResponse({ ok: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getAllByRole("combobox")[0], "crm");

      const permissionTable = await screen.findByRole("table", { name: "权限选择" });
      expect(permissionTable).toBeVisible();
      expect(fetchMock).not.toHaveBeenCalledWith("/console/api/v1/apps/crm/permission-tree", expect.anything());

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 退款" }));

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve" }));
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 dashboard.view" }));
      await user.type(screen.getByRole("textbox"), "处理跨部门工单");
      await user.click(screen.getByRole("button", { name: "提交申请" }));

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/portal/api/v1/me/access-requests",
          expect.objectContaining({
            method: "POST",
            credentials: "include",
            headers: expect.any(Object),
            body: JSON.stringify({
              app_key: "crm",
              request_type: "grant",
              role_keys: [],
              permission_keys: ["orders.refund.approve", "dashboard.view"],
              grant_type: "permanent",
              grant_expires_at: null,
              reason: "处理跨部门工单",
            }),
          }),
        ),
      );

      expect(await screen.findByRole("status")).toHaveTextContent("申请已提交");
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
