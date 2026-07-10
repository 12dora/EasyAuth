import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";

import { PortalPage } from "./PortalPage";

function renderPortalPageWithUser(currentUserId: string, initialEntry = "/portal/request") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route element={<Outlet context={{ currentUserId }} />}>
            <Route path="/portal/request" element={<PortalPage view="request" />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

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
          <Route path="/portal/request" element={<PortalPage view="request" />} />
          <Route path="/portal/requests" element={<PortalPage view="requests" />} />
          <Route path="/portal/expiring" element={<PortalPage view="expiring" />} />
          <Route path="/portal" element={<PortalPage view="grants" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderPortalPageStrict(initialEntry = "/portal/request") {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/portal/request" element={<PortalPage view="request" />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}

describe("PortalPage access request form", () => {
  test("StrictMode 下点击权限组行不会卡死", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
          authorization_groups: [],
          permission_groups: [
            {
              id: 1,
              app_key: "crm",
              type: "group",
              key: "crm.customer",
              name: "客户管理",
              permissions: [
                { id: 101, app_key: "crm", key: "crm.customer.read", name: "查看客户", scopes: [{ key: "SELF", name: "本人" }] },
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
      renderPortalPageStrict();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("row", { name: /客户管理/ }));

      expect(within(permissionTable).getByText("查看客户")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("StrictMode 下点击权限组权限范围 chip 后表单仍可提交", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
          authorization_groups: [],
          permission_groups: [
            {
              id: 1,
              app_key: "crm",
              type: "group",
              key: "crm.customer",
              name: "客户管理",
              permissions: [
                { id: 101, app_key: "crm", key: "crm.customer.read", name: "查看客户", scopes: [{ key: "SELF", name: "本人" }] },
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
      renderPortalPageStrict();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      const permissionTable = await screen.findByRole("table", { name: "权限选择" });
      const groupScopeChip = within(permissionTable).getByRole("checkbox", { name: "选择权限组 crm.customer 本人" });
      await user.click(groupScopeChip);

      await waitFor(() => expect(groupScopeChip).toBeChecked());
      await user.type(screen.getByLabelText("申请原因"), "申请查看客户");
      expect(screen.getByRole("button", { name: "提交申请" })).toBeEnabled();

      await user.click(screen.getByRole("button", { name: "提交申请" }));

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/portal/api/v1/me/access-requests",
          expect.objectContaining({
            method: "POST",
            body: JSON.stringify({
              app_key: "crm",
              request_type: "grant",
              authorization_group_keys: [],
              direct_grants: [{ permission: "crm.customer.read", scope: "SELF" }],
              approver_user_ids: ["manager-001"],
              grant_type: "permanent",
              grant_expires_at: null,
              reason: "申请查看客户",
            }),
          }),
        ),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("权限分类包含超过 50 项权限时可完整选择", async () => {
    const permissions = Array.from({ length: 51 }, (_, index) => ({
      id: index + 1,
      app_key: "easytrade",
      key: `document.record.${index}`,
      name: `单据权限 ${index + 1}`,
      scopes: [{ key: "ALL", name: "全部" }],
    }));
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "easytrade", name: "EasyTrade", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
          authorization_groups: [],
          permission_groups: [{
            id: 1,
            app_key: "easytrade",
            type: "group",
            key: "document",
            name: "单据",
            permissions,
          }],
          ungrouped_permissions: [],
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "EasyTrade (easytrade)" });
      await user.selectOptions(screen.getByLabelText("应用"), "easytrade");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择权限组 document 全部" }));

      expect(screen.getByText("已选 51 项")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

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
      expect(screen.getByText("当前应用未返回可直接申请的权限，可仅选择权限组发起申请。")).toBeVisible();
      expect(screen.getByRole("button", { name: "提交申请" })).toBeDisabled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("申请权限表单按单列流程展示核心字段", async () => {
    const fetchMock = permissionSelectorFetchMock({
      apps: [{ id: 1, app_key: "crm", name: "CRM" }],
      approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
      authorization_groups: [{ id: 11, app_key: "crm", key: "reader", kind: "role", name: "只读权限组" }],
      permission_groups: [],
      ungrouped_permissions: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();

      await screen.findByRole("option", { name: "CRM (crm)" });

      // 「直接权限」「审批人」为 group 语义字段(FF-10), 其可见标题渲染为带 id 的 <span> 而非 <label>。
      const labels = ["应用", "可申请权限组", "直接权限", "审批人", "授权期限", "过期时间", "申请原因"].map((label) =>
        screen.getByText(label, { selector: "label, span" }),
      );

      for (let index = 0; index < labels.length - 1; index += 1) {
        expect(labels[index].compareDocumentPosition(labels[index + 1]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      }
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

      // FF-5: 过期时间必须晚于当前时刻, 故填入相对当前时间的未来值(避免固定日期随时钟过期)。
      const future = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
      const futureLocal = new Date(future.getTime() - future.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
      fireEvent.change(screen.getByLabelText("过期时间"), { target: { value: futureLocal } });

      expect(submitButton).toBeEnabled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("FF-7: 申请人自己不出现在审批人候选中且默认审批人剔除自己", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["me", "boss"] }],
          approver_options: [
            { user_id: "me", name: "我本人" },
            { user_id: "boss", name: "老板" },
          ],
          authorization_groups: [],
          permission_groups: [],
          ungrouped_permissions: [],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPageWithUser("me");
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      // 默认审批人来自应用默认列表, 但必须剔除申请人自己(me)。
      expect(await screen.findByLabelText("选择审批人 boss")).toBeChecked();
      expect(screen.queryByLabelText("选择审批人 me")).not.toBeInTheDocument();

      // 即使搜索也搜不到自己。
      await user.type(screen.getByLabelText("搜索审批人"), "我本人");
      expect(screen.queryByLabelText("选择审批人 me")).not.toBeInTheDocument();
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
                        { key: "MANAGED_USERS", name: "管理用户" },
                        { key: "ALL", name: "全部" },
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

      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.read 本人" })).toBeVisible();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 dashboard.view 全局" })).toBeVisible();

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" }));
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 dashboard.view 全局" }));
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
                { permission: "orders.refund.approve", scope: "MANAGED_USERS" },
                { permission: "orders.refund.approve", scope: "ALL" },
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

  test("权限组行支持整行展开、父级权限范围 chip 和整棵子树选择", async () => {
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
                    { key: "MANAGED_USERS", name: "管理用户" },
                    { key: "ALL", name: "全部" },
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
                        { key: "MANAGED_USERS", name: "管理用户" },
                        { key: "ALL", name: "全部" },
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

      const groupAllChip = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" });
      await user.click(groupAllChip);
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(groupAllChip).toBeChecked();

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
                { permission: "orders.read", scope: "SELF" },
                { permission: "orders.read", scope: "MANAGED_USERS" },
                { permission: "orders.read", scope: "ALL" },
                { permission: "orders.refund.approve", scope: "SELF" },
                { permission: "orders.refund.approve", scope: "MANAGED_USERS" },
                { permission: "orders.refund.approve", scope: "ALL" },
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

  test("父级权限范围 chip 在只选择部分后代权限时显示半选状态", async () => {
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
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.read 本人" }));

      const groupScopeChip = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 本人" }) as HTMLInputElement;
      expect(groupScopeChip).not.toBeChecked();
      expect(groupScopeChip.indeterminate).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("收拢父权限组时不临时渲染未展开子组的权限", async () => {
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
              permissions: [{ id: 101, app_key: "crm", key: "orders.read", name: "查看订单", scopes: [{ key: "SELF", name: "本人" }] }],
              children: [
                {
                  id: 2,
                  app_key: "crm",
                  type: "group",
                  key: "orders.refund",
                  name: "退款",
                  permissions: [
                    { id: 102, app_key: "crm", key: "orders.refund.approve", name: "审批退款", scopes: [{ key: "SELF", name: "本人" }] },
                  ],
                },
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
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();

      await user.click(within(permissionTable).getByRole("button", { name: "收起 订单" }));

      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();
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

  test("MANAGED_USERS 目标缺少直属上级时提示补全审批人", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] }],
          approver_options: [
            { user_id: "app-owner", name: "应用负责人" },
            { user_id: "security-owner", name: "安全负责人" },
          ],
          authorization_groups: [],
          permission_groups: [],
          ungrouped_permissions: [
            {
              id: 101,
              app_key: "crm",
              key: "customer.assign",
              name: "分配客户",
              scopes: [{ key: "MANAGED_USERS", name: "下级用户" }],
              default_approver_user_ids: [],
              approver_resolution_status: "direct_manager_missing",
            },
          ],
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
      await user.click(screen.getByRole("checkbox", { name: "选择 customer.assign 下级用户" }));

      expect(await screen.findByText("未找到直属上级，请补全审批人")).toBeVisible();
      await user.type(screen.getByLabelText("搜索审批人"), "app-owner");
      expect(screen.getByLabelText("选择审批人 app-owner")).not.toBeChecked();
      expect(screen.getByRole("button", { name: "提交申请" })).toBeDisabled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("MANAGED_USERS 目标优先使用直属上级默认审批人且手动修改后不再覆盖", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["app-owner"] }],
          approver_options: [
            { user_id: "app-owner", name: "应用负责人" },
            { user_id: "direct-manager", name: "直属上级" },
            { user_id: "security-owner", name: "安全负责人" },
          ],
          authorization_groups: [],
          permission_groups: [],
          ungrouped_permissions: [
            {
              id: 101,
              app_key: "crm",
              key: "customer.assign",
              name: "分配客户",
              scopes: [{ key: "MANAGED_USERS", name: "下级用户" }],
              default_approver_user_ids: ["direct-manager"],
              approver_resolution_status: "direct_manager_resolved",
            },
            {
              id: 102,
              app_key: "crm",
              key: "customer.export",
              name: "导出客户",
              scopes: [{ key: "MANAGED_USERS", name: "下级用户" }],
              default_approver_user_ids: ["security-owner"],
              approver_resolution_status: "direct_manager_resolved",
            },
          ],
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
      await user.click(screen.getByRole("checkbox", { name: "选择 customer.assign 下级用户" }));
      expect(await screen.findByLabelText("选择审批人 direct-manager")).toBeChecked();

      await user.click(screen.getByLabelText("选择审批人 direct-manager"));
      await user.type(screen.getByLabelText("搜索审批人"), "owner");
      await user.click(screen.getByLabelText("选择审批人 app-owner"));
      await user.click(screen.getByRole("checkbox", { name: "选择 customer.export 下级用户" }));

      expect(screen.getByLabelText("选择审批人 app-owner")).toBeChecked();
      expect(screen.getByLabelText("选择审批人 security-owner")).not.toBeChecked();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("权限选择表格保留表头语义、展开状态和 checkbox 冒泡边界", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      expect(within(permissionTable).getByRole("columnheader", { name: "权限" })).toBeVisible();
      expect(within(permissionTable).getByRole("columnheader", { name: "权限 Key" })).toBeVisible();
      expect(within(permissionTable).getByRole("columnheader", { name: "权限范围" })).toBeVisible();
      expect(within(permissionTable).queryByRole("columnheader", { name: "scope" })).not.toBeInTheDocument();
      expect(within(permissionTable).queryByRole("columnheader", { name: "选择" })).not.toBeInTheDocument();
      expect(screen.queryByText(/已设置权限范围/)).not.toBeInTheDocument();
      expect(screen.queryByText(/当前显示/)).not.toBeInTheDocument();

      const expandButton = within(permissionTable).getByRole("button", { name: "展开 订单" });
      expect(expandButton).toHaveAttribute("aria-expanded", "false");
      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();

      const groupScopeChip = within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 本人" });
      await user.click(groupScopeChip);
      expect(groupScopeChip).toBeChecked();
      expect(within(permissionTable).getByRole("button", { name: "展开 订单" })).toHaveAttribute("aria-expanded", "false");
      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      expect(within(permissionTable).getByRole("button", { name: "收起 订单" })).toHaveAttribute("aria-expanded", "true");
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();

      await user.click(within(permissionTable).getByRole("button", { name: "收起 订单" }));
      expect(within(permissionTable).getByRole("button", { name: "展开 订单" })).toHaveAttribute("aria-expanded", "false");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("单权限范围权限通过权限范围 chip 选择", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      const selfChip = within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" });
      expect(selfChip).not.toBeChecked();

      await user.click(selfChip);
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).toBeChecked();
      expect(screen.getByText("已选 1 项")).toBeVisible();

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).not.toBeChecked();
      expect(screen.getByText("已选 0 项")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("多权限范围按递增关系自动补齐和收缩", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 退款" }));

      const self = within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" });
      const managed = within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理用户" });
      const all = within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" });

      await user.click(all);
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理用户" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).toBeChecked();
      expect(screen.getByText("已选 3 项")).toBeVisible();

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理用户" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).not.toBeChecked();
      expect(screen.getByText("已选 0 项")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("父条目权限范围 chip 操作整棵子树并显示半选态", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 退款" }));

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" }));

      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理用户" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).toBeChecked();

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" })).toHaveAttribute("aria-checked", "mixed");

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" })).toHaveAttribute("aria-checked", "false");
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理用户" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).not.toBeChecked();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("三层权限组收起后清理后代展开状态", async () => {
    const fetchMock = permissionSelectorFetchMock(threeLevelPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 退款" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 审计" }));
      expect(within(permissionTable).getByText("复核退款")).toBeVisible();

      vi.useFakeTimers();
      fireEvent.click(within(permissionTable).getByRole("button", { name: "收起 订单" }));
      fireEvent.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));

      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审计")).not.toBeInTheDocument();
      expect(within(permissionTable).queryByText("复核退款")).not.toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审计")).not.toBeInTheDocument();
      expect(within(permissionTable).queryByText("复核退款")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  test("权限列冻结并在展开收起时使用稳定动画状态", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });
      const permissionHeader = within(permissionTable).getByRole("columnheader", { name: "权限" });

      expect(permissionHeader).toHaveClass("permission-selector__sticky-column");

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      const enteringPermissionRow = within(permissionTable).getByText("查看订单").closest("tr");
      expect(enteringPermissionRow).toHaveClass("permission-selector__row--entering");
      expect(enteringPermissionRow?.querySelector(".permission-selector__sticky-column")).toBeTruthy();

      vi.useFakeTimers();
      fireEvent.click(within(permissionTable).getByRole("button", { name: "收起 订单" }));

      const exitingRows = permissionTable.querySelectorAll(".permission-selector__row--exiting");
      expect(exitingRows.length).toBeGreaterThan(0);
      expect(within(permissionTable).getAllByText("查看订单")).toHaveLength(1);

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  test("权限选择工具条展示状态并支持仅看已选过滤", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      const selectionStatus = screen.getByLabelText("权限选择状态");
      expect(within(selectionStatus).getByText("已选 0 项")).toBeVisible();
      expect(within(selectionStatus).getByRole("switch", { name: "仅看已选" })).toBeVisible();
      expect(screen.queryByText(/已设置权限范围/)).not.toBeInTheDocument();
      expect(screen.queryByText(/当前显示/)).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "展开全部" })).toBeVisible();
      expect(screen.getByRole("button", { name: "折叠全部" })).toBeVisible();
      expect(screen.getByRole("button", { name: "全选" })).toBeVisible();
      expect(screen.getByRole("button", { name: "清空" })).toBeVisible();
      await user.click(screen.getByLabelText("展开全选范围选项"));
      const selectAllScopeMenu = screen.getByRole("menu");
      expect(within(selectAllScopeMenu).getByRole("menuitem", { name: "本人" })).toBeVisible();
      expect(within(selectAllScopeMenu).getByRole("menuitem", { name: "管理范围" })).toBeVisible();
      expect(within(selectAllScopeMenu).getByRole("menuitem", { name: "全部" })).toBeVisible();

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" }));
      expect(within(screen.getByLabelText("权限选择状态")).getByText("已选 1 项")).toBeVisible();

      await user.click(within(screen.getByLabelText("权限选择状态")).getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("订单")).toBeVisible();
      expect(within(permissionTable).getByText("导出订单")).toBeVisible();
      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();
      expect(within(permissionTable).queryByText("查看看板")).not.toBeInTheDocument();
      expect(screen.getByText("第 1-2 条 / 共 2 条")).toBeVisible();

      await user.click(within(screen.getByLabelText("权限选择状态")).getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(within(permissionTable).getByText("查看看板")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("展开全部只作用于点击前当前页已有父条目", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(screen.getByRole("button", { name: "展开全部" }));

      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("工具条只操作当前页且翻页保留已选权限范围", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      await user.selectOptions(screen.getByLabelText("每页条目数"), "5");
      await user.click(screen.getByRole("button", { name: "展开全部" }));
      await user.click(screen.getByRole("button", { name: "全选" }));

      expect(within(screen.getByLabelText("权限选择状态")).getByText(/已选 [1-9]\d* 项/)).toBeVisible();

      if (screen.queryByRole("button", { name: "下一页" })?.hasAttribute("disabled") === false) {
        await user.click(screen.getByRole("button", { name: "下一页" }));
        expect(within(screen.getByLabelText("权限选择状态")).getByText(/已选 [1-9]\d* 项/)).toBeVisible();
        await user.click(screen.getByRole("button", { name: "上一页" }));
      }

      await user.click(screen.getByRole("button", { name: "清空" }));
      expect(screen.getByText("已选 0 项")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("工具条全选主按钮仍选择当前页所有权限范围", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(screen.getByRole("button", { name: "展开全部" }));
      await user.click(screen.getByRole("button", { name: "全选" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 退款" }));

      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.read 本人" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理用户" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 dashboard.view 全局" })).toBeChecked();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("工具条全选范围下拉按 scope 精确选择并提交时过滤不支持的权限范围", async () => {
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
                  key: "orders.refund.approve",
                  name: "审批退款",
                  scopes: [
                    { key: "SELF", name: "本人" },
                    { key: "MANAGED_USERS", name: "管理范围" },
                    { key: "ALL", name: "全部" },
                  ],
                },
                { id: 102, app_key: "crm", key: "orders.export", name: "导出订单", scopes: [{ key: "SELF", name: "本人" }] },
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
      await user.click(screen.getByRole("button", { name: "展开全部" }));

      await user.click(screen.getByLabelText("展开全选范围选项"));
      await user.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "本人" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理范围" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).toBeChecked();

      await user.click(screen.getByRole("button", { name: "清空" }));
      await user.click(screen.getByLabelText("展开全选范围选项"));
      await user.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "管理范围" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理范围" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).not.toBeChecked();

      await user.click(screen.getByRole("button", { name: "清空" }));
      await user.click(screen.getByLabelText("展开全选范围选项"));
      await user.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "全部" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 本人" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 管理范围" })).not.toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).not.toBeChecked();

      await user.type(screen.getByLabelText("申请原因"), "申请全部范围审批退款");
      await user.click(screen.getByRole("button", { name: "提交申请" }));

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/portal/api/v1/me/access-requests",
          expect.objectContaining({
            body: JSON.stringify({
              app_key: "crm",
              request_type: "grant",
              authorization_group_keys: [],
              direct_grants: [{ permission: "orders.refund.approve", scope: "ALL" }],
              approver_user_ids: ["app-owner"],
              grant_type: "permanent",
              grant_expires_at: null,
              reason: "申请全部范围审批退款",
            }),
          }),
        ),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("仅看已选无结果时显示表格内空状态", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(screen.getByRole("switch", { name: "仅看已选" }));
      expect(permissionTable).toBeVisible();
      expect(within(permissionTable).getByText("当前没有已选直接权限")).toBeVisible();
      expect(screen.queryByText(/当前显示/)).not.toBeInTheDocument();

      await user.click(screen.getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("订单")).toBeVisible();
      expect(within(permissionTable).getByText("查看看板")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("权限组 children 中的权限叶子参与渲染和父组权限范围选择", async () => {
    const fetchMock = permissionSelectorFetchMock({
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
          permissions: [],
          children: [
            { id: 101, app_key: "crm", key: "orders.audit", name: "审计订单", scopes: [{ key: "SELF", name: "本人" }] },
            {
              id: 2,
              app_key: "crm",
              type: "group",
              key: "orders.refund",
              name: "退款",
              permissions: [
                { id: 102, app_key: "crm", key: "orders.refund.approve", name: "审批退款", scopes: [{ key: "SELF", name: "本人" }] },
              ],
            },
          ],
        },
      ],
      ungrouped_permissions: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      expect(within(permissionTable).getByText("审计订单")).toBeVisible();

      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 本人" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.audit 本人" })).toBeChecked();
      expect(screen.getByText("已选 2 项")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("easytrade 权限组 direct permissions 与 children 重叠时展开收起活动日志不重复渲染权限", async () => {
    const createActivityLogPermission = {
      id: 101,
      app_key: "easytrade",
      key: "activity.log.create",
      name: "创建活动日志",
      scopes: [{ key: "SELF", name: "本人" }],
    };
    const readActivityLogPermission = {
      id: 102,
      app_key: "easytrade",
      key: "activity.log.read",
      name: "查看活动日志",
      scopes: [{ key: "SELF", name: "本人" }],
    };
    const fetchMock = permissionSelectorFetchMock({
      apps: [{ id: 1, app_key: "easytrade", name: "EasyTrade" }],
      approver_options: [],
      authorization_groups: [],
      permission_groups: [
        {
          id: 1,
          app_key: "easytrade",
          type: "group",
          key: "activity",
          name: "活动",
          permissions: [],
          children: [
            {
              id: 2,
              app_key: "easytrade",
              type: "group",
              key: "activity.log",
              name: "活动日志",
              permissions: [createActivityLogPermission, readActivityLogPermission],
              children: [createActivityLogPermission, readActivityLogPermission],
            },
          ],
        },
      ],
      ungrouped_permissions: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "EasyTrade (easytrade)" });
      await user.selectOptions(screen.getByLabelText("应用"), "easytrade");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 活动" }));
      await user.click(within(permissionTable).getByRole("button", { name: "展开 活动日志" }));

      expect(within(permissionTable).queryAllByText("activity.log.create")).toHaveLength(1);
      expect(within(permissionTable).queryAllByText("activity.log.read")).toHaveLength(1);

      await user.click(within(permissionTable).getByRole("button", { name: "收起 活动日志" }));
      await waitFor(() => expect(within(permissionTable).queryByText("activity.log.create")).not.toBeInTheDocument());
      expect(within(permissionTable).queryByText("activity.log.read")).not.toBeInTheDocument();

      for (let index = 0; index < 3; index += 1) {
        await user.click(within(permissionTable).getByRole("button", { name: "展开 活动日志" }));
        await waitFor(() => expect(within(permissionTable).queryAllByText("activity.log.create").length).toBeLessThanOrEqual(1));
        await user.click(within(permissionTable).getByRole("button", { name: "收起 活动日志" }));
        await waitFor(() => expect(within(permissionTable).queryByText("activity.log.create")).not.toBeInTheDocument());
      }
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("应用存在但没有直接权限时直接权限区域显示空状态", async () => {
    const fetchMock = permissionSelectorFetchMock(emptyDirectPermissionCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM (crm)" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      expect(await screen.findByRole("status")).toHaveTextContent("当前应用没有可直接申请的权限，可仅按权限组发起申请。");
      expect(screen.getByText("当前应用未返回可直接申请的权限，可仅选择权限组发起申请。")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("PortalPage tables", () => {
  test("我的权限使用服务端总数翻页，并展示 groups、expanded grants、source 和版本", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants?page=1&page_size=20") {
        return jsonResponse({
          data: [
            portalGrantRow({
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
            }),
          ],
          pagination: { page: 1, page_size: 20, total_items: 21, total_pages: 2 },
        });
      }
      if (url === "/portal/api/v1/me/grants?page=2&page_size=20") {
        return jsonResponse({
          data: [portalGrantRow({ app_key: "erp", app_name: "ERP" })],
          pagination: { page: 2, page_size: 20, total_items: 21, total_pages: 2 },
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
      expect(screen.getByText("第 1-1 条 / 共 21 条")).toBeVisible();

      const nextPage = screen.getByRole("button", { name: "下一页" });
      expect(nextPage).toBeEnabled();
      await userEvent.click(nextPage);

      expect(await screen.findByText("ERP")).toBeVisible();
      expect(fetchMock).toHaveBeenCalledWith(
        "/portal/api/v1/me/grants?page=2&page_size=20",
        expect.anything(),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("尾斜杠的即将过期视图保持显式 view，并把页大小发送给服务端", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants/expiring?page=1&page_size=20") {
        return jsonResponse({
          data: [portalGrantRow({ app_key: "crm", app_name: "即将过期 CRM", grant_type: "timed", grant_expires_at: "2026-07-15T10:00:00Z" })],
          pagination: { page: 1, page_size: 20, total_items: 25, total_pages: 2 },
        });
      }
      if (url === "/portal/api/v1/me/grants/expiring?page=1&page_size=50") {
        return jsonResponse({
          data: [portalGrantRow({ app_key: "crm", app_name: "即将过期 CRM", grant_type: "timed", grant_expires_at: "2026-07-15T10:00:00Z" })],
          pagination: { page: 1, page_size: 50, total_items: 25, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal/expiring/");

      expect(await screen.findByText("即将过期 CRM")).toBeVisible();
      expect(screen.getByRole("heading", { name: "即将过期" })).toBeVisible();

      await userEvent.selectOptions(screen.getByLabelText("每页条目数"), "50");

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/portal/api/v1/me/grants/expiring?page=1&page_size=50",
          expect.anything(),
        ),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("服务端总页数收缩时把当前页钳制到最后一页", async () => {
    let firstPageRequests = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants?page=1&page_size=20") {
        firstPageRequests += 1;
        return jsonResponse({
          data: [portalGrantRow({ app_name: firstPageRequests === 1 ? "初始第一页" : "收缩后第一页" })],
          pagination:
            firstPageRequests === 1
              ? { page: 1, page_size: 20, total_items: 21, total_pages: 2 }
              : { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      if (url === "/portal/api/v1/me/grants?page=2&page_size=20") {
        return jsonResponse({
          data: [],
          pagination: { page: 2, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal");
      expect(await screen.findByText("初始第一页")).toBeVisible();

      const nextPage = screen.getByRole("button", { name: "下一页" });
      expect(nextPage).toBeEnabled();
      await userEvent.click(nextPage);

      expect(await screen.findByText("收缩后第一页")).toBeVisible();
      expect(screen.getByText("1 / 1")).toBeVisible();
      expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
      expect(firstPageRequests).toBe(2);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("申请历史展示同意意见、限时到期时间，并使用服务端分页", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/access-requests?page=1&page_size=20") {
        return jsonResponse({
          data: [
            portalRequestRow({
              id: 9,
              app_key: "crm",
              app_name: "CRM",
              status: "approved",
              status_label: "已同意",
              grant_type: "timed",
              grant_expires_at: "2026-08-01T10:00:00Z",
              submitted_at: "2026-07-01T10:00:00Z",
              reason: "处理工单",
              decided_at: "2026-07-02T10:00:00Z",
              decision_comment: "同意按期开放",
              authorization_groups: [{ key: "sales-reader", kind: "role", name: "销售只读" }],
              direct_grants: [{ permission: "orders.refund.approve", permission_name: "审批退款", scope: "TEAM" }],
            }),
          ],
          pagination: { page: 1, page_size: 20, total_items: 21, total_pages: 2 },
        });
      }
      if (url === "/portal/api/v1/me/access-requests?page=2&page_size=20") {
        return jsonResponse({
          data: [portalRequestRow({ id: 21, app_key: "erp", app_name: "ERP", reason: "第二页申请" })],
          pagination: { page: 2, page_size: 20, total_items: 21, total_pages: 2 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal/requests");

      expect(await screen.findByText("销售只读 [role]")).toBeVisible();
      expect(screen.getByText("审批退款 (orders.refund.approve):TEAM")).toBeVisible();
      expect(screen.getByText(/审批意见：同意按期开放/)).toBeVisible();
      expect(screen.getAllByText(/2026/).length).toBeGreaterThanOrEqual(3);

      const nextPage = screen.getByRole("button", { name: "下一页" });
      expect(nextPage).toBeEnabled();
      await userEvent.click(nextPage);

      expect(await screen.findByText("ERP")).toBeVisible();
      expect(fetchMock).toHaveBeenCalledWith(
        "/portal/api/v1/me/access-requests?page=2&page_size=20",
        expect.anything(),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test.each([
    ["缺少 data", {}],
    ["data 为 null", { data: null, pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } }],
  ])("授权列表在 200 响应%s时明确报错", async (_caseName, payload) => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(payload)));

    try {
      renderPortalPage("/portal");

      expect(await screen.findByText("授权加载失败")).toBeVisible();
      expect(screen.getByText("授权列表响应格式无效：data 必须是数组")).toBeVisible();
      expect(screen.queryByText("暂无当前授权")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("申请历史在 data 为 null 时明确报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({ data: null, pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } }),
      ),
    );

    try {
      renderPortalPage("/portal/requests");

      expect(await screen.findByText("申请记录加载失败")).toBeVisible();
      expect(screen.getByText("申请记录列表响应格式无效：data 必须是数组")).toBeVisible();
      expect(screen.queryByText("暂无申请记录")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("授权列表行结构错误时明确报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({ data: [{}], pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 } }),
      ),
    );

    try {
      renderPortalPage("/portal");

      expect(await screen.findByText("授权加载失败")).toBeVisible();
      expect(screen.getByText("授权列表 data[0].app_key 必须是字符串")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

function portalGrantRow(overrides: Record<string, unknown> = {}) {
  return {
    app_key: "crm",
    app_name: "CRM",
    groups: [],
    grants: [],
    grant_version: 1,
    catalog_version: 1,
    snapshot_version: "1.1",
    grant_type: "permanent",
    grant_expires_at: null,
    ...overrides,
  };
}

function portalRequestRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    app_key: "crm",
    app_name: "CRM",
    request_type: "grant",
    status: "pending",
    status_label: "待审批",
    grant_type: "permanent",
    grant_expires_at: null,
    reason: "申请权限",
    submitted_at: "2026-07-01T10:00:00Z",
    authorization_groups: [],
    direct_grants: [],
    decided_at: null,
    decision_comment: "",
    ...overrides,
  };
}

const portalPermissionSelectorCatalog = {
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
        { id: 101, app_key: "crm", key: "orders.read", name: "查看订单", scopes: [{ key: "SELF", name: "本人" }] },
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
                { key: "MANAGED_USERS", name: "管理用户" },
                { key: "ALL", name: "全部" },
              ],
            },
          ],
        },
      ],
    },
  ],
  ungrouped_permissions: [{ id: 104, app_key: "crm", key: "dashboard.view", name: "查看看板", scopes: [{ key: "GLOBAL", name: "全局" }] }],
};

const threeLevelPermissionSelectorCatalog = {
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
      permissions: [],
      children: [
        {
          id: 2,
          app_key: "crm",
          type: "group",
          key: "orders.refund",
          name: "退款",
          permissions: [],
          children: [
            {
              id: 3,
              app_key: "crm",
              type: "group",
              key: "orders.refund.audit",
              name: "审计",
              permissions: [
                { id: 301, app_key: "crm", key: "orders.refund.audit.review", name: "复核退款", scopes: [{ key: "SELF", name: "本人" }] },
              ],
            },
          ],
        },
      ],
    },
  ],
  ungrouped_permissions: [],
};

const emptyDirectPermissionCatalog = {
  apps: [{ id: 1, app_key: "crm", name: "CRM" }],
  approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
  authorization_groups: [],
  permission_groups: [],
  ungrouped_permissions: [],
};

function permissionSelectorFetchMock(payload: unknown) {
  return vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url === "/portal/api/v1/request-catalog") {
      return jsonResponse(payload);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
