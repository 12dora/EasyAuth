import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { MatrixTab } from "./MatrixTab";
import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "../../../../components/antd/testing";

// antd Table 每次筛选都要重建整棵表格, jsdom 下比自研原语慢;
// 整套测试并行跑时表头筛选用例会逼近 20s, 因此本文件放宽到 30s。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

describe("MatrixTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("展示并保存 MANAGED_USERS grant 的管理范围策略", async () => {
    const authorizationGroupsPayload = {
      data: [
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
                resolver: "",
                enabled: false,
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
      if (url === "/console/api/v1/apps/demo/authorization-groups?include_inactive=true&page=1&page_size=100" && !init?.method) {
        return jsonResponse(authorizationGroupsPayload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({
          data: [
            { id: 20, key: "order.read", name: "订单读取", supported_scopes: ["MANAGED_USERS"] },
            { id: 21, key: "order.export", name: "订单导出", supported_scopes: ["SELF"] },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({
          data: [
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
        name_en: "",
        description: "管理范围角色",
        description_en: "",
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

  test("展示全部管理范围模式，直接保存不会改写策略", async () => {
    const payload = {
      data: [
        {
          id: 12,
          key: "team-manager",
          kind: "role",
          name: "团队主管",
          description: "",
          requestable: true,
          is_active: true,
          grants: [
            {
              permission: "order.read",
              scope: "MANAGED_USERS",
              is_active: true,
              managed_scope_policy: { mode: "easyauth_team", resolver: "easyauth_team", enabled: true },
              effective_managed_scope_policy: {
                resolver: "easyauth_team",
                enabled: true,
                source: "authorization_group_grant",
                inherited_from: null,
                health_status: "healthy",
              },
            },
            {
              permission: "order.export",
              scope: "MANAGED_USERS",
              is_active: true,
              managed_scope_policy: { mode: "union", resolver: "union", enabled: true },
              effective_managed_scope_policy: {
                resolver: "union",
                enabled: true,
                source: "authorization_group_grant",
                inherited_from: null,
                health_status: "healthy",
              },
            },
            {
              permission: "order.approve",
              scope: "MANAGED_USERS",
              is_active: true,
              managed_scope_policy: { mode: "inherit", resolver: "", enabled: false },
              effective_managed_scope_policy: {
                resolver: "dingtalk_manager_chain",
                enabled: true,
                source: "app_default",
                inherited_from: "app_default",
                health_status: "healthy",
              },
            },
            {
              permission: "order.manage",
              scope: "MANAGED_USERS",
              is_active: true,
              managed_scope_policy: { mode: "override", resolver: "dingtalk_manager_chain", enabled: true },
              effective_managed_scope_policy: {
                resolver: "dingtalk_manager_chain",
                enabled: true,
                source: "authorization_group_grant",
                inherited_from: null,
                health_status: "healthy",
              },
            },
            {
              permission: "order.disable",
              scope: "MANAGED_USERS",
              is_active: true,
              managed_scope_policy: { mode: "disabled", resolver: "disabled", enabled: true },
              effective_managed_scope_policy: null,
            },
          ],
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/authorization-groups?include_inactive=true&page=1&page_size=100" && !init?.method) {
        return jsonResponse(payload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({
          data: [
            { id: 20, key: "order.read", name: "订单读取", supported_scopes: ["MANAGED_USERS"] },
            { id: 21, key: "order.export", name: "订单导出", supported_scopes: ["MANAGED_USERS"] },
            { id: 22, key: "order.approve", name: "订单审批", supported_scopes: ["MANAGED_USERS"] },
            { id: 23, key: "order.manage", name: "订单管理", supported_scopes: ["MANAGED_USERS"] },
            { id: 24, key: "order.disable", name: "订单禁用", supported_scopes: ["MANAGED_USERS"] },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({ data: [{ key: "MANAGED_USERS", name: "被管理人员", is_active: true, display_order: 1 }] });
      }
      if (url === "/console/api/v1/apps/demo/authorization-groups/team-manager" && init?.method === "PATCH") {
        return jsonResponse(payload);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<MatrixTab appKey="demo" />);

    await screen.findByText("团队主管");
    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑授权组" });
    const teamRow = within(dialog).getByText("order.read / MANAGED_USERS").closest("tr") as HTMLTableRowElement;
    const unionRow = within(dialog).getByText("order.export / MANAGED_USERS").closest("tr") as HTMLTableRowElement;
    const inheritRow = within(dialog).getByText("order.approve / MANAGED_USERS").closest("tr") as HTMLTableRowElement;
    const overrideRow = within(dialog).getByText("order.manage / MANAGED_USERS").closest("tr") as HTMLTableRowElement;
    const disabledRow = within(dialog).getByText("order.disable / MANAGED_USERS").closest("tr") as HTMLTableRowElement;
    expect(within(teamRow).getByLabelText("order.read / MANAGED_USERS 管理范围计算方式")).toHaveValue("easyauth_team");
    expect(within(teamRow).getAllByText("按自定义团队").length).toBeGreaterThan(0);
    expect(within(unionRow).getByLabelText("order.export / MANAGED_USERS 管理范围计算方式")).toHaveValue("union");
    expect(within(unionRow).getAllByText("合并两者").length).toBeGreaterThan(0);
    expect(within(inheritRow).getByLabelText("order.approve / MANAGED_USERS 管理范围计算方式")).toHaveValue("inherit");
    expect(within(overrideRow).getByLabelText("order.manage / MANAGED_USERS 管理范围计算方式")).toHaveValue("dingtalk_manager_chain");
    expect(within(disabledRow).getByLabelText("order.disable / MANAGED_USERS 管理范围计算方式")).toHaveValue("disabled");

    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/authorization-groups/team-manager", "PATCH");
      const body = parseJsonBody(patchCall?.[1]) as { grants: Array<{ managed_scope_policy: unknown }> };
      expect(body.grants.map((grant) => grant.managed_scope_policy)).toEqual([
        { mode: "easyauth_team", resolver: "easyauth_team", enabled: true },
        { mode: "union", resolver: "union", enabled: true },
        { mode: "inherit", resolver: "", enabled: false },
        { mode: "override", resolver: "dingtalk_manager_chain", enabled: true },
        { mode: "disabled", resolver: "disabled", enabled: true },
      ]);
    });
  });
  test("同一批次内切换两个授权项状态时不会互相覆盖(FF-15)", async () => {
    const payload = {
      data: [
        {
          id: 30,
          key: "team",
          kind: "role",
          name: "团队角色",
          description: "",
          requestable: true,
          is_active: true,
          grants: [
            { permission: "order.read", scope: "SELF", is_active: true },
            { permission: "order.export", scope: "SELF", is_active: true },
          ],
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/authorization-groups?include_inactive=true&page=1&page_size=100" && !init?.method) {
        return jsonResponse(payload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({ data: [{ id: 40, key: "order.read", name: "读取", supported_scopes: ["SELF"] }, { id: 41, key: "order.export", name: "导出", supported_scopes: ["SELF"] }] });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({ data: [{ key: "SELF", name: "本人", is_active: true, display_order: 1 }] });
      }
      if (url === "/console/api/v1/apps/demo/authorization-groups/team" && init?.method === "PATCH") {
        return jsonResponse(payload);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<MatrixTab appKey="demo" />);

    await screen.findByText("团队角色");
    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑授权组" });

    const readRow = within(dialog).getByText("order.read / SELF").closest("tr") as HTMLTableRowElement;
    const exportRow = within(dialog).getByText("order.export / SELF").closest("tr") as HTMLTableRowElement;

    // 同一批次内(未重渲染前)连续切换两个授权项, 验证第二次不会用过期快照覆盖第一次。
    act(() => {
      fireEvent.click(within(readRow).getByRole("button", { name: "停用" }));
      fireEvent.click(within(exportRow).getByRole("button", { name: "停用" }));
    });

    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/authorization-groups/team", "PATCH");
      const body = parseJsonBody(patchCall?.[1]) as { grants: Array<{ is_active: boolean }> };
      expect(body.grants).toHaveLength(2);
      expect(body.grants.every((grant) => grant.is_active === false)).toBe(true);
    });
  });

  test("展示停用授权组并按管理能力重新启用", async () => {
    const payload = {
      data: [
        {
          id: 50,
          key: "disabled-role",
          kind: "role",
          name: "停用角色",
          description: "",
          requestable: false,
          is_active: false,
          grants: [{ permission: "order.read", scope: "SELF", is_active: true }],
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/authorization-groups?include_inactive=true&page=1&page_size=100" && !init?.method) {
        return jsonResponse(payload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({ data: [{ id: 60, key: "order.read", name: "读取", supported_scopes: ["SELF"] }] });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({ data: [{ key: "SELF", name: "本人", is_active: true, display_order: 1 }] });
      }
      if (url === "/console/api/v1/apps/demo/authorization-groups/disabled-role" && init?.method === "PATCH") {
        return jsonResponse(payload);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<MatrixTab appKey="demo" canManage />);

    await screen.findByText("停用角色");
    expect(screen.getByText("停用")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑授权组" });
    await user.click(within(dialog).getByRole("button", { name: "启用" }));
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/authorization-groups/disabled-role", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual(
        expect.objectContaining({
          key: "disabled-role",
          is_active: true,
        }),
      );
    });
  });

  test("授权组表头按类型和状态筛选, 分页渲染在同一行", async () => {
    const payload = {
      data: [
        { id: 70, key: "role-a", kind: "role", name: "角色甲", requestable: true, is_active: true, grants: [] },
        { id: 71, key: "bundle-a", kind: "bundle", name: "权限包甲", requestable: false, is_active: false, grants: [] },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/authorization-groups?include_inactive=true&page=1&page_size=100" && !init?.method) {
        return jsonResponse(payload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({ data: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    // antd 表格每次筛选都要整表重渲染, user-event 默认的事件间隔会让本用例逼近超时。
    const user = userEvent.setup({ delay: null });

    renderWithClient(<MatrixTab appKey="demo" />);

    await screen.findByText("角色甲");
    expect(bodyRowKeys()).toEqual(["role-a", "bundle-a"]);

    // 分页条: 区间文案 / 页码 / 每页条数必须在同一个 ul 里。
    const pagination = document.querySelector("ul.ant-pagination");
    expect(pagination).not.toBeNull();
    expect(pagination?.querySelector(".ant-pagination-total-text")).not.toBeNull();
    expect(pagination?.querySelector(".ant-pagination-options")).not.toBeNull();

    const kindDropdown = await openHeaderFilter(user, "类型");
    await user.click(within(kindDropdown).getByText("权限包"));
    await user.click(within(kindDropdown).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(bodyRowKeys()).toEqual(["bundle-a"]));

    await openHeaderFilter(user, "类型");
    await user.click(within(kindDropdown).getByText("权限包"));
    await user.click(within(kindDropdown).getByRole("button", { name: "确定" }));
    await waitFor(() => expect(bodyRowKeys()).toHaveLength(2));

    // 「可申请」与「启用」两枚徽章共用一个状态列, 筛选值按包含匹配。
    const statusDropdown = await openHeaderFilter(user, "状态");
    await user.click(within(statusDropdown).getByText("可申请"));
    await user.click(within(statusDropdown).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(bodyRowKeys()).toEqual(["role-a"]));
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

  renderWithAntd(
    <QueryClientProvider client={client}>
      {ui}
    </QueryClientProvider>,
  );
}

/** 打开指定表头的筛选下拉, 返回当前展开的那个下拉面板。 */

function bodyRowKeys(): string[] {
  return [...document.querySelectorAll(".ant-table-tbody tr.ant-table-row")].map(
    (row) => row.querySelector("td")?.textContent ?? "",
  );
}

function jsonResponse(payload: unknown) {
  const envelope = withPagination(payload);
  return new Response(JSON.stringify(envelope), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function withPagination(payload: unknown) {
  if (
    payload &&
    typeof payload === "object" &&
    "data" in payload &&
    Array.isArray(payload.data) &&
    !("pagination" in payload)
  ) {
    return {
      ...payload,
      pagination: {
        page: 1,
        page_size: 100,
        total_items: payload.data.length,
        total_pages: payload.data.length > 0 ? 1 : 0,
      },
    };
  }
  return payload;
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
