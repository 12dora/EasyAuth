import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { MemoryRouter, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, test, vi } from "vitest";

import { PortalPage } from "./PortalPage";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  renderWithAntd,
  sortByColumn,
} from "../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/排序/翻页都要重建整棵表格, 比自研原语慢得多,
// 整套用例并行跑时默认 5s 不够; 这里只放宽本文件的用例超时。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

// 权限详情浮层的 mouseLeaveDelay 是 0.2s(GrantPermissionsCell), 等够这段时间才能证明
// 指针走进浮层后它没被关掉。
const POPOVER_MOUSE_LEAVE_GRACE_MS = 400;

function renderPortalPageWithUser(currentUserId: string, initialEntry = "/portal/request") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  renderWithAntd(
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

  renderWithAntd(
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

/**
 * 我的权限 + 一个把路由 state 原样打印出来的申请页替身。
 *
 * 「更新权限」的契约是跳到 /portal/request 并把预填放进 react-router 的 location.state,
 * 消费这段 state 的是申请表单(另一条链路), 这里只验证发出去的东西对不对。
 */
function renderGrantsWithRequestStateProbe() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/portal"]}>
        <Routes>
          <Route path="/portal" element={<PortalPage view="grants" />} />
          <Route path="/portal/request" element={<RequestLocationStateProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function RequestLocationStateProbe() {
  const location = useLocation();
  return <pre data-testid="request-location-state">{JSON.stringify(location.state)}</pre>;
}

function renderPortalPageStrict(initialEntry = "/portal/request") {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  renderWithAntd(
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["manager-001"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["manager-001"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
      const submittedNotice = await screen.findByRole("status");
      expect(submittedNotice).toHaveTextContent("申请已提交");
      expect(submittedNotice).toHaveAttribute("aria-live", "polite");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("续期申请绑定当前授权修订并提交 renew payload", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
          authorization_groups: [],
          permission_groups: [],
          ungrouped_permissions: [
            { id: 101, app_key: "crm", key: "crm.customer.read", name: "查看客户", scopes: [{ key: "SELF", name: "本人" }] },
          ],
        });
      }
      if (url === "/portal/api/v1/me/grants?page=1&page_size=100") {
        return jsonResponse({
          data: [
            portalGrantRow({
              grant_id: 42,
              grant_revision: 7,
              grants: [portalExpandedGrant({ permission: "crm.customer.read", permission_name: "查看客户" })],
              grant_version: 7,
              catalog_version: 3,
              snapshot_version: "crm:7",
              grant_type: "timed",
              grant_expires_at: "2030-01-01T00:00:00+00:00",
            }),
          ],
          pagination: { page: 1, page_size: 100, total_items: 1, total_pages: 1 },
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("申请类型"), "renew");
      await screen.findByRole("option", { name: "CRM v7" });
      await user.selectOptions(screen.getByLabelText("基础授权"), "42");
      await user.type(screen.getByLabelText("过期时间"), "2030-02-01T09:00");
      await user.type(screen.getByLabelText("申请原因"), "延长期限");

      await user.click(screen.getByRole("button", { name: "提交申请" }));

      await waitFor(() => {
        const postCall = fetchMock.mock.calls.find(([input, init]) => String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST");
        expect(postCall).toBeDefined();
        expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({
          app_key: "crm",
          request_type: "renew",
          base_grant_id: 42,
          base_grant_revision: 7,
          direct_grants: [{ permission: "crm.customer.read", scope: "SELF" }],
          approver_user_ids: ["manager-001"],
          grant_type: "timed",
          reason: "延长期限",
        });
      });
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
          apps: [{ id: 1, app_key: "easytrade", name: "EasyTrade", alias: "", default_approver_user_ids: ["manager-001"] }],
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

      await screen.findByRole("option", { name: "EasyTrade" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
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

      await screen.findByRole("option", { name: "CRM" });
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
      apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
      approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
      authorization_groups: [{ id: 11, app_key: "crm", key: "reader", kind: "role", name: "只读权限组", grants: [] }],
      permission_groups: [],
      ungrouped_permissions: [],
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();

      await screen.findByRole("option", { name: "CRM" });

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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["manager-001"] }],
          approver_options: [{ user_id: "manager-001", name: "直属主管" }],
          authorization_groups: [
            { id: 11, app_key: "crm", key: "reader", kind: "role", name: "只读权限组", requestable: true, requires_approval: true, grants: [] },
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      await user.click(authorizationGroupCheckbox("只读权限组"));
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["me", "boss"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
          approver_options: [
            { user_id: "app-owner", name: "应用负责人" },
            { user_id: "ops-owner", name: "运营负责人" },
          ],
          authorization_groups: [
            { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", requestable: true, requires_approval: true, grants: [] },
            {
              id: 12,
              app_key: "crm",
              key: "order-ops",
              kind: "bundle",
              name: "订单运营包",
              requestable: true,
              requires_approval: true,
              default_approver_user_ids: ["ops-owner"],
              grants: [],
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      expect(screen.getByLabelText("选择审批人 app-owner")).toBeChecked();
      expect(screen.getByText("可申请权限组")).toBeVisible();
      expect(authorizationGroupCheckbox("销售只读")).toHaveAttribute("value", "sales-reader");
      expect(authorizationGroupCheckbox("订单运营包")).toHaveAttribute("value", "order-ops");

      await user.click(authorizationGroupCheckbox("订单运营包"));
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();

      vi.useFakeTimers();
      fireEvent.click(within(permissionTable).getByRole("button", { name: "收起 订单" }));

      // 收起的第一次渲染: 已展开的子行原地进入退场态, 未展开子组的权限一次都不会被渲染出来。
      expect(within(permissionTable).getByText("查看订单").closest("tr")).toHaveClass(
        "permission-selector__row--exiting",
      );
      expect(within(permissionTable).getByText("退款").closest("tr")).toHaveClass(
        "permission-selector__row--exiting",
      );
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(200);
      });

      expect(within(permissionTable).queryByText("查看订单")).not.toBeInTheDocument();
      expect(within(permissionTable).queryByText("退款")).not.toBeInTheDocument();
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  test("审批人列表只展示姓名和部门但仍支持按用户 ID 搜索", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse({
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["manager-001"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
            { id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] },
            { id: 2, app_key: "erp", name: "ERP", alias: "", default_approver_user_ids: ["finance-owner"] },
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
              grants: [],
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      expect(await screen.findByLabelText("选择审批人 app-owner")).toBeChecked();

      await user.click(screen.getByLabelText("选择审批人 app-owner"));
      await user.click(authorizationGroupCheckbox("订单运营包"));

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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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

      await screen.findByRole("option", { name: "CRM" });
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

      await screen.findByRole("option", { name: "CRM" });
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

  test("勾选权限范围 chip 不换掉单元格 DOM: 原节点仍在、仍聚焦, 再点一下立刻取消", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });
      await user.click(within(permissionTable).getByRole("button", { name: "展开 订单" }));

      const exportChip = within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" });
      const collapseButton = within(permissionTable).getByRole("button", { name: "收起 订单" });

      await user.click(exportChip);

      // 列定义是模块级常量, 勾选只换 data 与 meta: 单元格不会卸载重挂, 焦点因此留在原节点上,
      // 紧接着的第二次点击也还落在同一个节点上(节点被换掉时连点就会丢)。
      expect(exportChip).toBeInTheDocument();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.export 本人" })).toBe(exportChip);
      expect(document.activeElement).toBe(exportChip);
      expect(exportChip).toBeChecked();
      expect(within(permissionTable).getByRole("button", { name: "收起 订单" })).toBe(collapseButton);
      expect(screen.getByText("已选 1 项")).toBeVisible();

      await user.click(exportChip);

      expect(exportChip).toBeInTheDocument();
      expect(document.activeElement).toBe(exportChip);
      expect(exportChip).not.toBeChecked();
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

      await screen.findByRole("option", { name: "CRM" });
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

      await screen.findByRole("option", { name: "CRM" });
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

      // 半选态点一下补齐成全选(而不是再清空一次: 那样半选看起来像点不动)。
      await user.click(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" }));
      expect(within(permissionTable).getByRole("checkbox", { name: "选择权限组 orders 全部" })).toBeChecked();
      expect(within(permissionTable).getByRole("checkbox", { name: "选择 orders.refund.approve 全部" })).toBeChecked();

      // 全选态点一下清空整个范围。
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

      await screen.findByRole("option", { name: "CRM" });
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

      await screen.findByRole("option", { name: "CRM" });
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

      // 收起的第一次渲染就要带上退场态: 子行既不能消失, 也不能先卸载再挂回来(会闪一下),
      // 因此这里断言拿到的还是收起前那个 <tr> 节点。
      const exitingPermissionRow = within(permissionTable).getByText("查看订单").closest("tr");
      expect(exitingPermissionRow).toBe(enteringPermissionRow);
      expect(exitingPermissionRow).toHaveClass("permission-selector__row--exiting");
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

      await screen.findByRole("option", { name: "CRM" });
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

      await user.click(within(screen.getByLabelText("权限选择状态")).getByRole("switch", { name: "仅看已选" }));
      expect(within(permissionTable).getByText("查看订单")).toBeVisible();
      expect(within(permissionTable).getByText("查看看板")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("权限选择表格没有分页控件, 整棵权限树装在固定高度的滚动容器里", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      expect(screen.queryByLabelText("每页条目数")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "下一页" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "上一页" })).not.toBeInTheDocument();
      expect(screen.queryByText(/共 \d+ 条/)).not.toBeInTheDocument();

      const scrollContainer = permissionTable.parentElement;
      expect(scrollContainer).toHaveClass("max-h-[28rem]", "overflow-y-auto", "overflow-x-auto");
      expect(permissionTable.querySelector("thead")).toHaveClass("sticky", "top-0");
      // 表格铺满容器宽度, 同时保留最小宽度让窄布局回落到横向滚动。
      expect(permissionTable).toHaveClass("w-full", "min-w-[48rem]");

      // 「仅看已选」开关仍在, 只是不再有分页条陪着它。
      expect(screen.getByRole("switch", { name: "仅看已选" })).toBeVisible();
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");
      const permissionTable = await screen.findByRole("table", { name: "权限选择" });

      await user.click(screen.getByRole("button", { name: "展开全部" }));

      expect(within(permissionTable).getByText("退款")).toBeVisible();
      expect(within(permissionTable).queryByText("审批退款")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("工具条作用于全部已渲染行, 清空后回到零选中", async () => {
    const fetchMock = permissionSelectorFetchMock(portalPermissionSelectorCatalog);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      await user.click(screen.getByRole("button", { name: "展开全部" }));
      await user.click(screen.getByRole("button", { name: "全选" }));

      expect(within(screen.getByLabelText("权限选择状态")).getByText(/已选 [1-9]\d* 项/)).toBeVisible();

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

      await screen.findByRole("option", { name: "CRM" });
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
          apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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

      await screen.findByRole("option", { name: "CRM" });
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

      await screen.findByRole("option", { name: "CRM" });
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
      apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
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

      await screen.findByRole("option", { name: "CRM" });
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
      apps: [{ id: 1, app_key: "easytrade", name: "EasyTrade", alias: "" }],
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

      await screen.findByRole("option", { name: "EasyTrade" });
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

  test("从更新权限预填进来的已有权限可勾可取消, 取消后权限组落地为直接申请", async () => {
    const submittedPayloads: unknown[] = [];
    const fetchMock = coveredPermissionRequestFetchMock(submittedPayloads);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalRequestWithPrefill("7");
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByLabelText("基础授权")).toHaveValue("7"));
      expect(authorizationGroupCheckbox("只读")).toBeChecked();

      await screen.findByRole("table", { name: "权限选择" });
      await user.click(permissionSelectorChip("展开 订单", "button"));

      // 已由权限组授予的权限: 勾选且可编辑, 权限组表头因此能到全勾态。
      await waitFor(() => expect(permissionSelectorChip("选择 orders.read 本人")).toBeChecked());
      expect(permissionSelectorChip("选择 orders.read 本人")).toBeEnabled();
      expect(permissionSelectorChip("选择 orders.export 本人")).toBeChecked();
      expect(permissionSelectorChip("选择 orders.export 本人")).toBeEnabled();
      expect(permissionSelectorChip("选择权限组 orders 本人")).toBeChecked();

      await user.click(permissionSelectorChip("选择 orders.read 本人"));

      expect(authorizationGroupCheckbox("只读")).not.toBeChecked();
      expect(permissionSelectorChip("选择 orders.read 本人")).not.toBeChecked();
      expect(permissionSelectorChip("选择 orders.export 本人")).toBeChecked();
      expect(await screen.findByRole("status")).toHaveTextContent("已取消覆盖该权限的权限组，其覆盖的其余权限已转为单独申请。");

      await user.type(screen.getByLabelText("申请原因"), "只保留导出订单");
      await user.click(screen.getByRole("button", { name: "提交申请" }));

      await waitFor(() => expect(submittedPayloads).toHaveLength(1));
      expect(submittedPayloads[0]).toMatchObject({
        request_type: "change",
        base_grant_id: 7,
        base_grant_revision: 3,
        authorization_group_keys: [],
        direct_grants: [{ permission: "orders.export", scope: "SELF" }],
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("权限组表头在已有权限全勾时点一下清空整个范围", async () => {
    const fetchMock = coveredPermissionRequestFetchMock([]);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalRequestWithPrefill("7");
      const user = userEvent.setup();

      await waitFor(() => expect(authorizationGroupCheckbox("只读")).toBeChecked());
      await screen.findByRole("table", { name: "权限选择" });
      await user.click(permissionSelectorChip("展开 订单", "button"));

      await user.click(permissionSelectorChip("选择权限组 orders 本人"));

      expect(authorizationGroupCheckbox("只读")).not.toBeChecked();
      expect(permissionSelectorChip("选择 orders.read 本人")).not.toBeChecked();
      expect(permissionSelectorChip("选择 orders.export 本人")).not.toBeChecked();
      expect(permissionSelectorChip("选择权限组 orders 本人")).not.toBeChecked();
      expect(screen.getByText("已选 0 项")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("续期申请的申请目标整体只读", async () => {
    const fetchMock = coveredPermissionRequestFetchMock([]);
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("申请类型"), "renew");
      await screen.findByRole("option", { name: "CRM v3" });
      await user.selectOptions(screen.getByLabelText("基础授权"), "7");

      // 后端要求续期目标与基础授权完全一致, 目标只能照抄不能改。
      await waitFor(() => expect(authorizationGroupCheckbox("只读")).toBeChecked());
      expect(authorizationGroupCheckbox("只读")).toBeDisabled();
      expect(screen.getByLabelText("应用")).toBeDisabled();

      // PermissionSelector 的只读态作用在整行上(见 PermissionSelectorBody), 不是逐个 disabled。
      await screen.findByRole("table", { name: "权限选择" });
      expect(permissionSelectorChip("选择权限组 orders 本人").closest("tr")).toHaveClass("pointer-events-none");
      expect(permissionSelectorChip("选择权限组 orders 本人").closest("tr")).toHaveAttribute("inert");

      // 工具栏不在表格行里, 只读态必须自己带 native disabled: 否则点下去会撞上动作层的续期守卫。
      expect(screen.getByRole("button", { name: "全选" })).toBeDisabled();
      expect(screen.getByLabelText("展开全选范围选项")).toBeDisabled();
      expect(screen.getByRole("button", { name: "清空" })).toBeDisabled();
      // 只看已选与展开/折叠只改视图, 不动目标: 只读态下仍然可用。
      expect(within(screen.getByLabelText("权限选择状态")).getByRole("switch", { name: "仅看已选" })).toBeEnabled();
      expect(screen.getByRole("button", { name: "展开全部" })).toBeEnabled();

      await user.click(screen.getByRole("button", { name: "全选" }));
      await user.click(screen.getByRole("button", { name: "清空" }));
      await user.click(screen.getByLabelText("展开全选范围选项"));

      expect(screen.queryByRole("menu")).not.toBeInTheDocument();
      expect(authorizationGroupCheckbox("只读")).toBeChecked();
      expect(within(screen.getByLabelText("权限选择状态")).getByText("已选 0 项")).toBeVisible();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("撤销申请只能往下减: 基础授权之外的权限组、权限范围和批量全选入口都禁用", async () => {
    const fetchMock = revokeRequestFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage();
      const user = userEvent.setup();

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("申请类型"), "revoke");
      await screen.findByRole("option", { name: "CRM v3" });
      await user.selectOptions(screen.getByLabelText("基础授权"), "7");

      // 撤销提交的目标是"撤销后保留下来的授权", 后端要求它是基础授权的子集: 加进新东西必被拒。
      await waitFor(() => expect(authorizationGroupCheckbox("只读")).toBeChecked());
      expect(authorizationGroupCheckbox("只读")).toBeEnabled();
      expect(authorizationGroupCheckbox("删除")).toBeDisabled();

      await screen.findByRole("table", { name: "权限选择" });
      await user.click(permissionSelectorChip("展开 订单", "button"));

      expect(permissionSelectorChip("选择 orders.read 本人")).toBeEnabled();
      expect(permissionSelectorChip("选择 orders.export 本人")).toBeEnabled();
      expect(permissionSelectorChip("选择 orders.delete 本人")).toBeDisabled();
      // 表头 chip 的选中方向会把 orders.delete 一起带进来, 因此同样禁用。
      expect(permissionSelectorChip("选择权限组 orders 本人")).toBeDisabled();

      // 全选与按范围选择都会越界; 清空是纯减法(等于撤销全部), 仍然可用。
      expect(screen.getByRole("button", { name: "全选" })).toBeDisabled();
      expect(screen.getByLabelText("展开全选范围选项")).toBeDisabled();
      expect(screen.getByRole("button", { name: "清空" })).toBeEnabled();

      // 取消权限组覆盖的权限 = 整组不再保留, 之后这些权限也进不了保留范围。
      await user.click(permissionSelectorChip("选择 orders.read 本人"));
      expect(authorizationGroupCheckbox("只读")).not.toBeChecked();
      await waitFor(() => expect(permissionSelectorChip("选择 orders.read 本人")).toBeDisabled());
      expect(permissionSelectorChip("选择 orders.export 本人")).toBeDisabled();
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

      await screen.findByRole("option", { name: "CRM" });
      await user.selectOptions(screen.getByLabelText("应用"), "crm");

      expect(await screen.findByRole("status")).toHaveTextContent("当前应用没有可直接申请的权限，可仅按权限组发起申请。");
      expect(screen.getByText("当前应用未返回可直接申请的权限，可仅选择权限组发起申请。")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("PortalPage tables", () => {
  test("我的权限使用服务端总数翻页，权限组列只给组名、权限详情列只给条数", async () => {
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
                portalExpandedGrant({ source_type: "group", source_key: "sales-reader" }),
                portalExpandedGrant({
                  permission: "dashboard.view",
                  permission_name: "查看看板",
                  permission_name_en: "View dashboard",
                  scope: "GLOBAL",
                  scope_name: "全局",
                  scope_name_en: "Global",
                }),
              ],
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

      // 权限组列不再带 [角色] 后缀; 权限明细不再拼成一长串 key。
      expect(await screen.findByText("销售只读")).toBeVisible();
      expect(screen.queryByText("销售只读 [角色]")).not.toBeInTheDocument();
      expect(screen.getByText("2 项权限")).toBeVisible();
      expect(screen.queryByText(/orders\.read:SELF/)).not.toBeInTheDocument();
      expect(screen.queryByText(/group:sales-reader/)).not.toBeInTheDocument();

      const table = screen.getByRole("table", { name: "我的授权列表" });
      expect(within(table).getByRole("columnheader", { name: "权限详情" })).toBeVisible();
      expect(within(table).getByRole("columnheader", { name: "操作" })).toBeVisible();
      expect(within(table).queryByRole("columnheader", { name: "来源" })).not.toBeInTheDocument();
      expect(within(table).queryByRole("columnheader", { name: "版本" })).not.toBeInTheDocument();
      expect(within(table).queryByRole("columnheader", { name: "期限" })).not.toBeInTheDocument();

      // antd 的区间文案按 page/page_size 推算, 不按当前页实际行数收窄。
      expect(screen.getByText("第 1-20 条 / 共 21 条")).toBeVisible();

      const nextPage = screen.getByTitle("下一页");
      expect(nextPage).not.toHaveClass("ant-pagination-disabled");
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

  test("权限详情浮层按来源分组列出「权限名 · 范围名」, 悬停与聚焦都能打开", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants?page=1&page_size=20") {
        return jsonResponse({
          data: [
            portalGrantRow({
              groups: [{ key: "sales-reader", kind: "role", name: "销售只读" }],
              grants: [
                portalExpandedGrant({ source_type: "group", source_key: "sales-reader" }),
                portalExpandedGrant({
                  permission: "orders.export",
                  permission_name: "导出订单",
                  scope: "ALL",
                  scope_name: "全部",
                  source_type: "group",
                  source_key: "sales-reader",
                }),
                portalExpandedGrant({ permission: "dashboard.view", permission_name: "查看看板", scope_name: "全局" }),
              ],
            }),
          ],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal");
      const user = userEvent.setup();

      const trigger = await screen.findByRole("button", { name: "3 项权限" });
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

      await user.hover(trigger);
      const tooltip = await screen.findByRole("tooltip");
      await waitFor(() => {
        expect(tooltip).toBeVisible();
      });
      expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
      // 角色带来的权限归在角色名下, 直接授权单列一组。
      expect(within(tooltip).getByText("销售只读")).toBeVisible();
      expect(within(tooltip).getByText("直接授权")).toBeVisible();
      expect(within(tooltip).getByText("查看订单 · 本人")).toBeVisible();
      expect(within(tooltip).getByText("导出订单 · 全部")).toBeVisible();
      expect(within(tooltip).getByText("查看看板 · 全局")).toBeVisible();
      // 长列表靠浮层自己滚: 滚动盒就是这一层。
      expect(tooltip).toHaveClass("max-h-80", "overflow-y-auto", "max-w-[28rem]");

      // 指针从触发器走进浮层不能把它关掉, 否则滚动条永远够不着; 等过了关闭延时再断言。
      await user.hover(tooltip);
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, POPOVER_MOUSE_LEAVE_GRACE_MS));
      });
      expect(tooltip).toBeVisible();

      await user.unhover(tooltip);
      await waitFor(() => {
        expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
      });

      // 键盘用户: 触发器可聚焦, 聚焦即展开。
      act(() => {
        trigger.focus();
      });
      await waitFor(() => {
        expect(screen.getByRole("tooltip")).toBeVisible();
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("过期时间列合并期限: 长期给标签, 限时给时刻, 混合期限两者都给", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants?page=1&page_size=20") {
        return jsonResponse({
          data: [
            portalGrantRow({ grant_id: 1, app_name: "长期应用", grant_type: "permanent", grant_expires_at: null }),
            portalGrantRow({ grant_id: 2, app_name: "限时应用", grant_type: "timed", grant_expires_at: "2026-08-01T10:00:00Z" }),
            portalGrantRow({ grant_id: 3, app_name: "混合应用", grant_type: "mixed", grant_expires_at: "2026-09-01T10:00:00Z" }),
          ],
          pagination: { page: 1, page_size: 20, total_items: 3, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal");

      expect(await screen.findByText("长期应用")).toBeVisible();
      expect(expiresAtCellText("长期应用")).toBe("长期");
      expect(expiresAtCellText("限时应用")).toMatch(/^2026\/08\/01/);
      expect(expiresAtCellText("混合应用")).toMatch(/^2026\/09\/01.*（混合期限）$/);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("更新权限按钮带着变更预填跳到申请页", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants?page=1&page_size=20") {
        return jsonResponse({
          data: [portalGrantRow({ grant_id: 42, app_name: "CRM" })],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderGrantsWithRequestStateProbe();

      await screen.findByText("CRM");
      await userEvent.click(screen.getByRole("button", { name: "更新权限" }));

      const state = await screen.findByTestId("request-location-state");
      expect(JSON.parse(state.textContent ?? "null")).toEqual({
        accessRequestPrefill: { requestType: "change", baseGrantId: "42" },
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("我的权限表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (!url.startsWith("/portal/api/v1/me/grants?")) {
        throw new Error(`Unexpected fetch: ${url}`);
      }
      const page = new URLSearchParams(url.split("?")[1]).get("page") ?? "1";
      return jsonResponse({
        data: [portalGrantRow({ grant_id: Number(page), app_key: `app-${page}`, app_name: `应用${page}` })],
        pagination: { page: Number(page), page_size: 20, total_items: 21, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    try {
      renderPortalPage("/portal");

      // 表格不设默认排序: 首屏不带 ordering, 表头也没有指示器。
      expect(await screen.findByText("应用1")).toBeVisible();
      expect(columnSortOrder("应用")).toBeNull();

      await user.click(screen.getByTitle("下一页"));
      await screen.findByText("应用2");

      await sortByColumn(user, "过期时间");
      await waitFor(() =>
        expect(lastFetchUrl(fetchMock)).toBe("/portal/api/v1/me/grants?page=1&page_size=20&ordering=expires_at"),
      );
      expect(columnSortOrder("过期时间")).toBe("ascend");
      expect(columnSortOrder("应用")).toBeNull();

      await sortByColumn(user, "过期时间");
      await waitFor(() =>
        expect(lastFetchUrl(fetchMock)).toBe("/portal/api/v1/me/grants?page=1&page_size=20&ordering=-expires_at"),
      );
      expect(columnSortOrder("过期时间")).toBe("descend");
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

      await userEvent.click(document.querySelector(".ant-pagination-options .ant-select-selector") as HTMLElement);
      await userEvent.click(await screen.findByTitle("50 条/页"));

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

      const nextPage = screen.getByTitle("下一页");
      expect(nextPage).not.toHaveClass("ant-pagination-disabled");
      await userEvent.click(nextPage);

      expect(await screen.findByText("收缩后第一页")).toBeVisible();
      expect(screen.getByText("第 1-1 条 / 共 1 条")).toBeVisible();
      expect(screen.getByTitle("下一页")).toHaveClass("ant-pagination-disabled");
      expect(firstPageRequests).toBe(2);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  /** 我的权限 / 即将过期两张表共用同一份列定义, 同一条不变量对它们同样成立。 */
  test("我的权限表格每列都声明宽度, 且 minWidth 等于列宽之和", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/me/grants?page=1&page_size=20") {
        return jsonResponse({
          data: [portalGrantRow({ app_name: "CRM" })],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderPortalPage("/portal");
      await screen.findByText("CRM");

      const table = screen.getByRole("table", { name: "我的授权列表" });
      const widths = declaredColumnWidths(table);

      // 应用 / 权限组 / 权限详情 / 过期时间 / 操作。
      expect(widths).toEqual([200, 200, 160, 220, 160]);
      expect(widths).toHaveLength(table.querySelectorAll("thead.ant-table-thead th").length);
      expect(tableScrollWidth(table)).toBe(widths.reduce((sum, width) => sum + width, 0));
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

  test("授权表的应用列按「别名 + 技术名」展示", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({
          data: [portalGrantRow({ app_key: "easycustoms", app_name: "EasyCustoms", app_alias: "海关数据" })],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        }),
      ),
    );

    try {
      renderPortalPage("/portal");
      // 展示名的拼法由 formatAppDisplayName 单点决定(它自己有用例), 这里只锁「这一列用它」。
      expect(await screen.findByText(formatAppDisplayName({ name: "EasyCustoms", alias: "海关数据" }))).toBeVisible();
      // 技术名仍以等宽 app_key 的形式留在第二行, 供对接排查用。
      expect(screen.getByText("easycustoms")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("授权列表缺少 app_alias 时明确报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => {
        const row = portalGrantRow();
        delete (row as Record<string, unknown>).app_alias;
        return jsonResponse({ data: [row], pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 } });
      }),
    );

    try {
      renderPortalPage("/portal");

      expect(await screen.findByText("授权加载失败")).toBeVisible();
      expect(screen.getByText("授权列表 data[0].app_alias 必须是字符串")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("授权列表缺少权限显示名时明确报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () => {
        const grant = portalExpandedGrant();
        delete (grant as Record<string, unknown>).scope_name_en;
        return jsonResponse({
          data: [portalGrantRow({ grants: [grant] })],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }),
    );

    try {
      renderPortalPage("/portal");

      expect(await screen.findByText("授权加载失败")).toBeVisible();
      expect(screen.getByText("授权列表 data[0].grants[0].scope_name_en 必须是字符串")).toBeVisible();
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

/**
 * 表格 `<colgroup>` 里各列声明的像素宽度, 按列序返回。
 *
 * 列上没写 width 时 rc-table 渲染出的 `<col>` 不带 `style.width`, 这里直接抛错 ——
 * 「每列都声明了宽度」正是要锁住的不变量, 不能悄悄按 0 计入求和。
 */
function declaredColumnWidths(table: HTMLElement): number[] {
  return Array.from(table.querySelectorAll<HTMLTableColElement>("colgroup > col")).map((col, index) => {
    const width = col.style.width;
    if (!width.endsWith("px")) {
      throw new Error(`第 ${index + 1} 列没有声明像素列宽, 实际为 ${JSON.stringify(width)}`);
    }
    return Number.parseFloat(width);
  });
}

/** AppTable 传下去的 minWidth(即 `scroll.x`)由 rc-table 写在滚动 `<table>` 的内联 width 上。 */
function tableScrollWidth(table: HTMLElement): number {
  const width = table.style.width;
  if (!width.endsWith("px")) {
    throw new Error(`表格没有把 minWidth 写成像素宽度, 实际为 ${JSON.stringify(width)}`);
  }
  return Number.parseFloat(width);
}

/** 授权表里某一行的「过期时间」单元格文本; 该列固定是应用 / 权限组 / 权限详情之后的第四列。 */
function expiresAtCellText(appName: string): string {
  const row = screen.getByText(appName).closest("tr");
  if (row === null) {
    throw new Error(`未找到应用 ${appName} 所在的表格行`);
  }
  return within(row).getAllByRole("cell")[3].textContent ?? "";
}

function lastFetchUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return String(fetchMock.mock.calls.at(-1)?.[0] ?? "");
}

function portalGrantRow(overrides: Record<string, unknown> = {}) {
  return {
    app_key: "crm",
    app_name: "CRM",
    app_alias: "",
    grant_id: 1,
    groups: [],
    grants: [],
    grant_revision: 1,
    grant_version: 1,
    catalog_version: 1,
    snapshot_version: "1.1",
    grant_type: "permanent",
    grant_expires_at: null,
    ...overrides,
  };
}

/** 展开授权项: permission / scope 是 key, *_name / *_name_en 是目录里的双语显示名。 */
function portalExpandedGrant(overrides: Record<string, unknown> = {}) {
  return {
    permission: "orders.read",
    permission_name: "查看订单",
    permission_name_en: "View orders",
    scope: "SELF",
    scope_name: "本人",
    scope_name_en: "Self",
    source_type: "direct",
    source_key: null,
    ...overrides,
  };
}

const portalPermissionSelectorCatalog = {
  apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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
  apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
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
  apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
  approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
  authorization_groups: [],
  permission_groups: [],
  ungrouped_permissions: [],
};

/**
 * 权限选择表格里的一个控件。
 *
 * 变更申请要等基础授权列表加载完, 期间权限选择器会先让位给占位态, 表格节点会被换掉,
 * 所以这里每次都重新查一遍表格, 不缓存节点。
 */
function permissionSelectorChip(name: string, role: "checkbox" | "button" = "checkbox") {
  return within(screen.getByRole("table", { name: "权限选择" })).getByRole(role, { name });
}

/** 权限组是多选勾选框(一条授权可以挂多个权限组), 按本地化组名定位。 */
function authorizationGroupCheckbox(name: string) {
  return within(screen.getByRole("group", { name: "可申请权限组" })).getByRole("checkbox", { name });
}

/** 「更新权限」跳转过来的变更申请: 路由 state 里带着基础授权预填。 */
function renderPortalRequestWithPrefill(baseGrantId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/portal/request",
            state: { accessRequestPrefill: { requestType: "change", baseGrantId } },
          },
        ]}
      >
        <Routes>
          <Route path="/portal/request" element={<PortalPage view="request" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/**
 * 一条「权限全部来自权限组 reader」的当前授权 + 同一批权限可单独申请的目录:
 * 用来验证预填进来的已有权限可编辑、以及取消其中一项时权限组落地成逐项直接申请。
 */
function coveredPermissionRequestFetchMock(submittedPayloads: unknown[]) {
  const catalog = {
    apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
    approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
    authorization_groups: [
      {
        id: 11,
        app_key: "crm",
        key: "reader",
        kind: "role",
        name: "只读",
        requestable: true,
        grants: [
          { permission_key: "orders.read", scope_key: "SELF" },
          { permission_key: "orders.export", scope_key: "SELF" },
        ],
      },
    ],
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
  };
  const grantList = {
    data: [
      portalGrantRow({
        grant_id: 7,
        grant_revision: 3,
        groups: [{ key: "reader", kind: "role", name: "只读" }],
        grants: [
          portalExpandedGrant({ source_type: "group", source_key: "reader" }),
          portalExpandedGrant({
            permission: "orders.export",
            permission_name: "导出订单",
            permission_name_en: "Export orders",
            source_type: "group",
            source_key: "reader",
          }),
        ],
      }),
    ],
    pagination: { page: 1, page_size: 100, total_items: 1, total_pages: 1 },
  };

  return vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/portal/api/v1/request-catalog") {
      return jsonResponse(catalog);
    }
    if (url === "/portal/api/v1/me/grants?page=1&page_size=100") {
      return jsonResponse(grantList);
    }
    if (url === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
      submittedPayloads.push(JSON.parse(String(init.body)));
      return jsonResponse({ access_request: { id: 1 } });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

/**
 * 撤销申请的固定场景: 基础授权只有权限组 reader(覆盖 orders.read / orders.export),
 * 目录里另外还有它不含的权限组 deleter 与权限 orders.delete —— 这两样都不能加进保留范围。
 */
function revokeRequestFetchMock() {
  const catalog = {
    apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["app-owner"] }],
    approver_options: [{ user_id: "app-owner", name: "应用负责人" }],
    authorization_groups: [
      {
        id: 11,
        app_key: "crm",
        key: "reader",
        kind: "role",
        name: "只读",
        requestable: true,
        grants: [
          { permission_key: "orders.read", scope_key: "SELF" },
          { permission_key: "orders.export", scope_key: "SELF" },
        ],
      },
      {
        id: 12,
        app_key: "crm",
        key: "deleter",
        kind: "role",
        name: "删除",
        requestable: true,
        grants: [{ permission_key: "orders.delete", scope_key: "SELF" }],
      },
    ],
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
          { id: 103, app_key: "crm", key: "orders.delete", name: "删除订单", scopes: [{ key: "SELF", name: "本人" }] },
        ],
      },
    ],
    ungrouped_permissions: [],
  };
  const grantList = {
    data: [
      portalGrantRow({
        grant_id: 7,
        grant_revision: 3,
        groups: [{ key: "reader", kind: "role", name: "只读" }],
        grants: [
          portalExpandedGrant({ source_type: "group", source_key: "reader" }),
          portalExpandedGrant({
            permission: "orders.export",
            permission_name: "导出订单",
            permission_name_en: "Export orders",
            source_type: "group",
            source_key: "reader",
          }),
        ],
      }),
    ],
    pagination: { page: 1, page_size: 100, total_items: 1, total_pages: 1 },
  };

  return vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url === "/portal/api/v1/request-catalog") {
      return jsonResponse(catalog);
    }
    if (url === "/portal/api/v1/me/grants?page=1&page_size=100") {
      return jsonResponse(grantList);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

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
