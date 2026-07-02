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
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      expect(screen.getByLabelText("过期时间")).toBeDisabled();
      await user.type(screen.getByLabelText("申请原因"), "需要申请权限");

      expect(await screen.findByRole("status")).toHaveTextContent("当前应用没有可直接申请的权限，可仅按权限组发起申请。");
      expect(screen.queryByText("未发现可选直接权限")).not.toBeInTheDocument();
      expect(screen.queryByText("暂无可选直接权限")).not.toBeInTheDocument();
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      await user.selectOptions(screen.getByLabelText("可申请权限组"), "reader");
      await user.type(screen.getByLabelText("申请原因"), "临时处理跨部门工单");
      await user.selectOptions(screen.getByLabelText("授权期限"), "timed");

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
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] }],
          approver_options: [
            { user_id: "app-owner", name: "应用负责人" },
            { user_id: "ops-owner", name: "运营负责人" },
          ],
          authorization_groups: [
            { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", requestable: true, requires_approval: true },
            {
              id: 12,
              app_key: "crm",
              key: "order-ops",
              kind: "bundle",
              name: "订单运营包",
              requestable: true,
              requires_approval: true,
              default_approver_user_ids: ["ops-owner"],
            },
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      expect(screen.getByLabelText("选择审批人 app-owner")).toBeChecked();
      expect(screen.getByText("可申请权限组")).toBeVisible();
      expect(screen.getByRole("option", { name: "销售只读 [role] (sales-reader)" })).toBeVisible();
      expect(screen.getByRole("option", { name: "订单运营包 [bundle] (order-ops)" })).toBeVisible();

      await user.selectOptions(screen.getByLabelText("可申请权限组"), "order-ops");
      expect(screen.getByLabelText("选择审批人 ops-owner")).toBeChecked();
      await user.type(screen.getByLabelText("申请原因"), "处理订单运营");
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
              approver_user_ids: ["ops-owner"],
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] }],
          approver_options: [
            { user_id: "app-owner", name: "应用负责人" },
            { user_id: "security-owner", name: "安全负责人" },
          ],
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
                      default_approver_user_ids: ["security-owner"],
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

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
      await user.type(screen.getByLabelText("申请原因"), "处理跨部门工单");
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
              approver_user_ids: ["security-owner"],
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

  test("权限组行支持整行展开、父级勾选和父级 scope 批量应用", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] }],
          approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
          authorization_groups: [],
          permission_groups: [
            {
              id: 1,
              app_key: "crm",
              type: "group",
              key: "orders",
              name: "订单",
              permissions: [
                {
                  id: 101,
                  app_key: "crm",
                  key: "orders.read",
                  name: "查看订单",
                  scopes: [
                    { key: "SELF", name: "本人" },
                    { key: "TEAM", name: "团队" },
                  ],
                },
                { id: 102, app_key: "crm", key: "orders.export", name: "导出订单", scopes: [{ key: "SELF", name: "本人" }] },
              ],
              children: [
                {
                  id: 2,
                  app_key: "crm",
                  type: "group",
                  key: "orders.refund",
                  name: "退款",
                  permissions: [
                    {
                      id: 103,
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("row", { name: /订单/ }));
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();

      const groupCheckbox = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders" });
      await user.click(groupCheckbox);
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(groupCheckbox).toBeChecked();

      await user.selectOptions(within(permissionTable).getByLabelText("orders 权限组 scope"), "TEAM");
      await user.type(screen.getByLabelText("申请原因"), "批量申请订单权限");
      await user.click(screen.getByRole("button", { name: "提交申请" }));

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/portal/api/v1/me/access-requests",
          expect.objectContaining({
            body: JSON.stringify({
              app_key: "crm",
              request_type: "grant",
              authorization_group_keys: [],
              direct_grants: [
                { permission: "orders.read", scope: "TEAM" },
                { permission: "orders.export", scope: "SELF" },
                { permission: "orders.refund.approve", scope: "TEAM" },
              ],
              approver_user_ids: ["app-owner"],
              grant_type: "permanent",
              grant_expires_at: null,
              reason: "批量申请订单权限",
            }),
          }),
        ),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("父级 checkbox 在只选择部分后代权限时显示半选状态", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM" }],
          approver_options: [],
          authorization_groups: [],
          permission_groups: [
            {
              id: 1,
              app_key: "crm",
              type: "group",
              key: "orders",
              name: "订单",
              permissions: [
                { id: 101, app_key: "crm", key: "orders.read", name: "查看订单", scopes: [{ key: "SELF", name: "本人" }] },
                { id: 102, app_key: "crm", key: "orders.export", name: "导出订单", scopes: [{ key: "SELF", name: "本人" }] },
              ],
            },
          ],
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.read" }));

      const groupCheckbox = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders" }) as HTMLInputElement;
      expect(groupCheckbox).not.toBeChecked();
      expect(groupCheckbox.indeterminate).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("审批人列表只展示姓名和部门但仍支持按用户 ID 搜索", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管", department: "销售部", email: "manager@example.test" }],
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      expect(await screen.findByText("直属主管")).toBeVisible();
      expect(screen.getByText("· 销售部")).toBeVisible();
      expect(screen.queryByText("manager-001")).not.toBeInTheDocument();

      await user.clear(screen.getByLabelText("搜索审批人"));
      await user.type(screen.getByLabelText("搜索审批人"), "manager-001");
      expect(screen.getByText("直属主管")).toBeVisible();
      expect(screen.getByText("· 销售部")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("手动修改审批人后目标变化不覆盖，应用切换重置为新应用默认", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [
            { id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] },
            { id: 2, app_key: "erp", name: "ERP", default_approver_user_ids: ["finance-owner"] },
          ],
          approver_options: [
            { user_id: "app-owner", name: "应用负责人" },
            { user_id: "ops-owner", name: "运营负责人" },
            { user_id: "finance-owner", name: "财务负责人" },
          ],
          authorization_groups: [
            {
              id: 12,
              app_key: "crm",
              key: "order-ops",
              kind: "bundle",
              name: "订单运营包",
              requestable: true,
              requires_approval: true,
              default_approver_user_ids: ["ops-owner"],
            },
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
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      expect(await screen.findByLabelText("选择审批人 app-owner")).toBeChecked();

      await user.click(screen.getByLabelText("选择审批人 app-owner"));
      await user.selectOptions(screen.getByLabelText("可申请权限组"), "order-ops");

      await user.type(screen.getByLabelText("搜索审批人"), "owner");
      expect(screen.getByLabelText("选择审批人 app-owner")).not.toBeChecked();
      expect(screen.getByLabelText("选择审批人 ops-owner")).not.toBeChecked();

      await user.selectOptions(screen.getByLabelText("应用"), "erp");
      expect(await screen.findByLabelText("选择审批人 finance-owner")).toBeChecked();
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
      expect(screen.getByText("授权 3 / 目录 7 / 快照 3.7")).toBeVisible();
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
