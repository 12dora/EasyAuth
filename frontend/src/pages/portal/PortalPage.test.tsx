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
          <Route path="/portal/requests" element={<PortalPage />} />
          <Route path="/portal" element={<PortalPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortalPage access request form", () => {
  test("未选择权限组或直接权限时不能提交申请", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          authorization_groups: [],
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
          authorization_groups: [
            { id: 11, app_key: "crm", key: "reader", kind: "role", name: "只读权限组", requestable: true, requires_approval: true },
          ],
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

  test("提交 authorization group 申请", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          authorization_groups: [
            { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", requestable: true, requires_approval: true },
            { id: 12, app_key: "crm", key: "order-ops", kind: "bundle", name: "订单运营包", requestable: true, requires_approval: true },
          ],
          permission_groups: [],
          ungrouped_permissions: [],
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
      expect(screen.getByText("可申请权限组")).toBeVisible();
      expect(screen.getByRole("option", { name: "销售只读 [role] (sales-reader)" })).toBeVisible();
      expect(screen.getByRole("option", { name: "订单运营包 [bundle] (order-ops)" })).toBeVisible();

      await user.selectOptions(screen.getAllByRole("combobox")[1], "order-ops");
      await user.type(screen.getByRole("textbox"), "处理订单运营");
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
              authorization_group_keys: ["order-ops"],
              direct_grants: [],
              grant_type: "permanent",
              grant_expires_at: null,
              reason: "处理订单运营",
            }),
          }),
        ),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("按权限树展开并勾选 direct scoped grant 后提交 direct_grants", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          authorization_groups: [],
          permission_groups: [
            {
              id: 1,
              app_key: "crm",
              type: "group",
              key: "orders",
              name: "订单",
              permissions: [{ id: 101, app_key: "crm", key: "orders.read", name: "查看订单", scopes: [{ key: "SELF", name: "本人" }] }],
              children: [
                {
                  id: 2,
                  app_key: "crm",
                  type: "group",
                  key: "orders.refund",
                  name: "退款",
                  permissions: [
                    {
                      id: 102,
                      app_key: "crm",
                      key: "orders.refund.approve",
                      name: "审批退款",
                      scopes: [
                        { key: "SELF", name: "本人" },
                        { key: "TEAM", name: "团队" },
                      ],
                    },
                  ],
                },
              ],
            },
          ],
          ungrouped_permissions: [{ id: 103, app_key: "crm", key: "dashboard.view", name: "查看看板", scopes: [{ key: "GLOBAL", name: "全局" }] }],
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

      expect(within(permissionTable).getByLabelText("orders.read scope")).toHaveValue("SELF");
      expect(within(permissionTable).getByLabelText("dashboard.view scope")).toHaveValue("GLOBAL");

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve SELF" }));
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve TEAM" }));
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
              authorization_group_keys: [],
              direct_grants: [
                { permission: "orders.refund.approve", scope: "SELF" },
                { permission: "orders.refund.approve", scope: "TEAM" },
                { permission: "dashboard.view", scope: "GLOBAL" },
              ],
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

describe("PortalPage tables", () => {
  test("我的权限展示 groups、expanded grants、source 和版本", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants") {
        return jsonResponse({
          items: [
            {
              app_key: "crm",
              app_name: "CRM",
              groups: [{ key: "sales-reader", kind: "role", name: "销售只读" }],
              grants: [
                { permission: "orders.read", scope: "SELF", source_type: "group", source_key: "sales-reader" },
                { permission: "dashboard.view", scope: "GLOBAL", source_type: "direct", source_key: "" },
              ],
              grant_version: 3,
              catalog_version: 7,
              snapshot_version: "3.7",
              grant_type: "permanent",
              grant_expires_at: null,
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal");

      expect(await screen.findByText("销售只读 [role]")).toBeVisible();
      expect(screen.getByText(/orders\.read:SELF/)).toBeVisible();
      expect(screen.getByText(/group:sales-reader/)).toBeVisible();
      expect(screen.getByText(/dashboard\.view:GLOBAL/)).toBeVisible();
      expect(screen.getByText(/direct/)).toBeVisible();
      expect(screen.getByText("grant 3 / catalog 7 / snapshot 3.7")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("/portal/requests 的申请详情展示 authorization groups 和 direct grants", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/access-requests") {
        return jsonResponse({
          items: [
            {
              id: 9,
              app_key: "crm",
              app_name: "CRM",
              status: "pending",
              status_label: "待审批",
              grant_type: "permanent",
              submitted_at: "2026-07-01T10:00:00Z",
              reason: "处理工单",
              authorization_groups: [{ key: "sales-reader", kind: "role", name: "销售只读" }],
              direct_grants: [{ permission: "orders.refund.approve", permission_name: "审批退款", scope: "TEAM" }],
            },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal/requests");

      expect(await screen.findByText("销售只读 [role]")).toBeVisible();
      expect(screen.getByText("审批退款 (orders.refund.approve):TEAM")).toBeVisible();
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
