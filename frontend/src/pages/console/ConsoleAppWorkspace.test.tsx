import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { lazy, Suspense, type ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ToastProvider } from "../../components/ui/Toast";
import { ManifestTab } from "./workspace/tabs/ManifestTab";
import { QueryTestTab } from "./workspace/tabs/QueryTestTab";
import { RulesTab } from "./workspace/tabs/RulesTab";

const LazyConsoleAppWorkspace = lazy(() =>
  import("./ConsoleAppWorkspace").then((module) => ({ default: module.ConsoleAppWorkspace })),
);

const appPayload = {
  app: {
    id: 1,
    app_key: "demo",
    name: "Demo App",
    description: "Demo console app",
  },
};

describe("ConsoleAppWorkspace", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.dataset.currentUserRole = "";
  });

  test("catalog 展示 scope 字典、权限分组和权限 scope 配置", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/permission-tree") {
        return jsonResponse({ groups: [] });
      }
      if (url === "/console/api/v1/apps/demo/permission-groups") {
        return jsonResponse({
          data: [{ id: 10, key: "finance", name: "财务权限", description: "财务域", display_order: 10, is_active: true }],
        });
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({
          data: [
            {
              id: 20,
              key: "invoice.read",
              name: "发票读取",
              group_key: "finance",
              supported_scopes: ["SELF", "TEAM"],
              risk_level: "high",
              is_active: true,
            },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({
          data: [
            { key: "SELF", name: "本人", description: "仅本人数据", is_active: true, display_order: 1 },
            { key: "TEAM", name: "团队", description: "团队数据", is_active: false, display_order: 2 },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWorkspace("/console/apps/demo?tab=catalog");

    await screen.findByRole("heading", { name: "权限分组" });
    expect(screen.getByRole("heading", { name: "权限范围" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "权限" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "新建" })).toHaveLength(3);
    await screen.findByText("SELF");
    expect(screen.getByText("团队")).toBeInTheDocument();
    expect(screen.getAllByText("停用").length).toBeGreaterThan(0);
    expect(screen.getAllByText("finance").length).toBeGreaterThan(0);
    expect(screen.getByText("财务权限")).toBeInTheDocument();
    expect(screen.getByText("invoice.read")).toBeInTheDocument();
    expect(screen.getByText("SELF、TEAM")).toBeInTheDocument();
    expect(screen.getAllByText("高").length).toBeGreaterThan(0);
  });

  test("切换工作台 tab 时更新 URL 并显示目标内容", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/configuration-status") {
        return jsonResponse({ status: "ready", data: [] });
      }
      if (url === "/console/api/v1/apps/demo/memberships") {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/apps/demo/approval-rules") {
        return jsonResponse({ data: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo");

    expect(await screen.findByTestId("location")).toHaveTextContent("/console/apps/demo");
    await user.click(screen.getByRole("tab", { name: "审批规则" }));

    expect(await screen.findByRole("heading", { name: "审批规则" })).toBeVisible();
    expect(screen.getByTestId("location")).toHaveTextContent("/console/apps/demo?tab=rules");
  });

  test("同一 tab 从应用 A 导航到应用 B 时销毁旧应用的本地状态和在途结果", async () => {
    let resolveOldQuery!: (response: Response) => void;
    const oldQueryResponse = new Promise<Response>((resolve) => {
      resolveOldQuery = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/second") {
        return jsonResponse({ app: { ...appPayload.app, app_key: "second", name: "Second App" } });
      }
      if (url === "/console/api/v1/apps/demo/permission-query-tests" && init?.method === "POST") {
        return oldQueryResponse;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=test");

    const userInput = await screen.findByLabelText("用户 ID");
    await user.type(userInput, "alice");
    await user.type(screen.getByLabelText("Bearer token"), "app-a-secret");
    await user.click(screen.getByRole("button", { name: "执行联调" }));
    await user.click(screen.getByRole("button", { name: "导航到第二个应用" }));

    expect(await screen.findByRole("heading", { name: "Second App" })).toBeInTheDocument();
    expect(screen.getByLabelText("用户 ID")).toHaveValue("");
    expect(screen.getByLabelText("Bearer token")).toHaveValue("");

    await act(async () => {
      resolveOldQuery(jsonResponse({
        app_key: "demo",
        user_id: "alice",
        allowed: true,
        source: "app-a-result",
        groups: [],
        grants: [],
      }));
      await oldQueryResponse;
    });
    expect(screen.queryByText("app-a-result")).not.toBeInTheDocument();
  });

  test("管理范围权威快照格式错误时禁止编辑和保存，重试成功后才开放", async () => {
    let managedScopeReadCount = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse({ app: { ...appPayload.app, can_manage: true } });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && !init?.method) {
        managedScopeReadCount += 1;
        return managedScopeReadCount === 1
          ? jsonResponse({})
          : jsonResponse({ managed_scope_policy: null, effective_managed_scope_policy: null });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=managed-scope");

    expect(await screen.findByText("管理范围策略响应格式无效。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();
    expect(screen.queryByLabelText("应用默认管理范围计算方式")).not.toBeInTheDocument();
    expect(findFetchCall(fetchMock, "/console/api/v1/apps/demo/managed-scope-policy", "PATCH")).toBeUndefined();

    await user.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByLabelText("应用默认管理范围计算方式")).toHaveValue("unconfigured");
    expect(screen.getByRole("button", { name: "保存设置" })).toBeEnabled();
  });

  test("管理范围重新挂载时等待最新权威读取，读取失败后保持关闭直到重试成功", async () => {
    let rejectReload!: (reason: Error) => void;
    const reloadResponse = new Promise<Response>((_resolve, reject) => {
      rejectReload = reject;
    });
    let managedScopeReadCount = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse({ app: { ...appPayload.app, can_manage: true } });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && !init?.method) {
        managedScopeReadCount += 1;
        if (managedScopeReadCount === 1) {
          return jsonResponse({
            managed_scope_policy: { mode: "override", resolver: "dingtalk_manager_chain", enabled: true },
            effective_managed_scope_policy: {
              resolver: "dingtalk_manager_chain",
              enabled: true,
              source: "app_default",
              health_status: "healthy",
            },
          });
        }
        if (managedScopeReadCount === 2) {
          return reloadResponse;
        }
        return jsonResponse({ managed_scope_policy: null, effective_managed_scope_policy: null });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=managed-scope");

    expect(await screen.findByLabelText("应用默认管理范围计算方式")).toHaveValue("dingtalk_manager_chain");
    await user.click(screen.getByRole("tab", { name: "联调" }));
    await user.click(screen.getByRole("tab", { name: "管理范围" }));
    await waitFor(() => expect(managedScopeReadCount).toBe(2));

    expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();
    expect(screen.queryByLabelText("应用默认管理范围计算方式")).not.toBeInTheDocument();

    rejectReload(new Error("重新读取失败"));

    expect(await screen.findByText("重新读取失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存设置" })).toBeDisabled();
    expect(screen.queryByLabelText("应用默认管理范围计算方式")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByLabelText("应用默认管理范围计算方式")).toHaveValue("unconfigured");
    expect(screen.getByRole("button", { name: "保存设置" })).toBeEnabled();
  });

  test("管理范围 tab 读取并保存应用默认 MANAGED_USERS 策略", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse({ app: { ...appPayload.app, can_manage: true } });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && !init?.method) {
        return jsonResponse({
          managed_scope_policy: null,
          effective_managed_scope_policy: null,
        });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && init?.method === "PATCH") {
        return jsonResponse({
          managed_scope_policy: { mode: "override", resolver: "dingtalk_manager_chain", enabled: true },
          effective_managed_scope_policy: {
            resolver: "dingtalk_manager_chain",
            enabled: true,
            source: "app_default",
            health_status: "healthy",
            health_message: "已启用",
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo");

    await user.click(await screen.findByRole("tab", { name: "管理范围" }));

    expect(await screen.findByRole("heading", { name: "管理范围" })).toBeInTheDocument();
    expect(screen.getAllByText("未配置").length).toBeGreaterThan(0);
    const select = screen.getByLabelText("应用默认管理范围计算方式");
    expect(within(select).getByRole("option", { name: "按钉钉汇报线（自动）" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "按自定义团队" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "合并两者" })).toBeInTheDocument();
    expect(within(select).getByRole("option", { name: "不启用" })).toBeInTheDocument();

    await user.selectOptions(select, "dingtalk_manager_chain");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/managed-scope-policy", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        managed_scope_policy: {
          mode: "override",
          resolver: "dingtalk_manager_chain",
          enabled: true,
        },
      });
    });
    await waitFor(() => expect(screen.getAllByText("按钉钉汇报线（自动）").length).toBeGreaterThan(1));
  });

  test("管理范围 tab 选择按自定义团队时展示团队管理入口并保存 easyauth_team", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse({ app: { ...appPayload.app, can_manage: true } });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && !init?.method) {
        return jsonResponse({
          managed_scope_policy: null,
          effective_managed_scope_policy: null,
        });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && init?.method === "PATCH") {
        return jsonResponse({
          managed_scope_policy: { mode: "override", resolver: "easyauth_team", enabled: true },
          effective_managed_scope_policy: {
            resolver: "easyauth_team",
            enabled: true,
            source: "app_default",
            health_status: "healthy",
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=managed-scope");

    const select = await screen.findByLabelText("应用默认管理范围计算方式");
    await waitFor(() => expect(select).toBeEnabled());
    expect(screen.queryByRole("link", { name: "前往团队管理" })).not.toBeInTheDocument();

    await user.selectOptions(select, "easyauth_team");

    expect(screen.getByText(/成员在「团队管理」维护/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "前往团队管理" })).toHaveAttribute("href", "/console/teams");

    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/managed-scope-policy", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        managed_scope_policy: {
          mode: "override",
          resolver: "easyauth_team",
          enabled: true,
        },
      });
    });
    await waitFor(() => expect(screen.getAllByText("按自定义团队").length).toBeGreaterThan(1));
  });

  test("管理范围 tab 可保存不启用应用默认策略", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse({ app: { ...appPayload.app, can_manage: true } });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && !init?.method) {
        return jsonResponse({
          managed_scope_policy: { mode: "override", resolver: "dingtalk_manager_chain", enabled: true },
          effective_managed_scope_policy: {
            resolver: "dingtalk_manager_chain",
            enabled: true,
            source: "app_default",
            health_status: "healthy",
          },
        });
      }
      if (url === "/console/api/v1/apps/demo/managed-scope-policy" && init?.method === "PATCH") {
        return jsonResponse({
          managed_scope_policy: { mode: "disabled", resolver: "disabled", enabled: false },
          effective_managed_scope_policy: {
            resolver: "disabled",
            enabled: true,
            source: "app_default",
            health_status: "disabled",
            health_message: "应用默认策略已停用",
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=managed-scope");

    const select = await screen.findByLabelText("应用默认管理范围计算方式");
    await waitFor(() => expect(select).toHaveValue("dingtalk_manager_chain"));

    await user.selectOptions(select, "disabled");
    await user.click(screen.getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/managed-scope-policy", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        managed_scope_policy: {
          mode: "disabled",
          resolver: "disabled",
          enabled: false,
        },
      });
    });
    await screen.findByText("应用默认策略已停用");
  });

  test("授权组保存 payload 包含 permission 和 scope", async () => {
    const authorizationGroupsPayload = {
      version: "catalog-v1",
      data: [
        {
          id: 10,
          key: "accountant",
          kind: "role",
          name: "会计只读",
          description: "财务只读角色",
          requestable: true,
          is_active: true,
          grants: [{ permission: "invoice.read", scope: "SELF", is_active: true }],
        },
      ],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/authorization-groups" && !init?.method) {
        return jsonResponse(authorizationGroupsPayload);
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({
          data: [
            { id: 20, key: "invoice.read", name: "发票读取", supported_scopes: ["SELF", "TEAM"], risk_level: "standard" },
            { id: 21, key: "invoice.export", name: "发票导出", supported_scopes: ["TEAM"], risk_level: "high" },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({
          data: [
            { key: "SELF", name: "本人", is_active: true, display_order: 1 },
            { key: "TEAM", name: "团队", is_active: true, display_order: 2 },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/authorization-groups/accountant" && init?.method === "PATCH") {
        return jsonResponse(authorizationGroupsPayload);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=matrix");

    await screen.findByRole("heading", { name: "授权组管理" });
    await screen.findByText("会计只读");
    expect(screen.getAllByText("角色").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑授权组" });
    expect(within(dialog).getByText("invoice.read / SELF")).toBeInTheDocument();
    await user.selectOptions(within(dialog).getByLabelText("授权权限"), "invoice.export");
    await user.selectOptions(within(dialog).getByLabelText("授权范围"), "TEAM");
    await user.click(within(dialog).getByRole("button", { name: "添加授权项" }));
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/authorization-groups/accountant", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        key: "accountant",
        kind: "role",
        name: "会计只读",
        description: "财务只读角色",
        requestable: true,
        is_active: true,
        grants: [
          { permission: "invoice.read", scope: "SELF", is_active: true },
          { permission: "invoice.export", scope: "TEAM", is_active: true },
        ],
      });
    });
  });

  test("关闭一次性 static token 弹窗后明文不再留在页面", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/apps/demo/credentials/static-tokens" && init?.method === "POST") {
        return jsonResponse({
          one_time_secret: { kind: "static_token", token: "plain-secret-once" },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=credentials");

    expect(await screen.findByRole("heading", { name: "凭据" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "新建" }));
    const dialog = await screen.findByRole("dialog", { name: "新建凭据" });
    await user.type(within(dialog).getByLabelText("凭据名称"), "primary token");
    await user.click(within(dialog).getByRole("button", { name: "静态 token" }));

    expect(await screen.findByText("plain-secret-once")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "关闭" }));

    await waitFor(() => expect(screen.queryByText("plain-secret-once")).not.toBeInTheDocument());
  });

  test("OAuth client 行不展示轮换操作且禁用时调用 oauth-clients 路径", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({
          data: [
            { id: 101, kind: "oauth_client", name: "OAuth Primary", client_id: "oauth-client-1", is_active: true },
            { id: 202, kind: "static_token", name: "Static Primary", is_active: true },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/credentials/oauth-clients/101/disable" && init?.method === "POST") {
        return jsonResponse({ ok: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=credentials");

    const oauthRow = (await screen.findByText("OAuth Primary")).closest("tr");
    expect(oauthRow).not.toBeNull();
    expect(within(oauthRow as HTMLTableRowElement).queryByRole("button", { name: "轮换" })).not.toBeInTheDocument();

    await user.click(within(oauthRow as HTMLTableRowElement).getByRole("button", { name: "禁用" }));

    await waitFor(() => {
      expect(findFetchCall(fetchMock, "/console/api/v1/apps/demo/credentials/oauth-clients/101/disable", "POST")).toBeDefined();
    });
  });

  test("联调成功后清空 Bearer token 输入框", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/permission-query-tests" && init?.method === "POST") {
        return jsonResponse({
          app_key: "demo",
          user_id: "alice",
          allowed: true,
          roles: ["admin"],
          permissions: ["invoice.read"],
          version: "v1",
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=test");

    await user.type(screen.getByLabelText("用户 ID"), "alice");
    const tokenInput = screen.getByLabelText<HTMLInputElement>("Bearer token");
    await user.type(tokenInput, "secret-bearer-token");
    await user.click(screen.getByRole("button", { name: "执行联调" }));

    await waitFor(() => expect(tokenInput).toHaveValue(""));
  });

  test("manifest 预览成功后显示差异", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/permission-template-imports/preview" && init?.method === "POST") {
        return jsonResponse({
          preview_id: "preview-1",
          diff: {
            added: [{ type: "permission", key: "invoice.approve", name: "发票审批" }],
            changed: [{ type: "group", key: "finance", before: "财务", after: "财务中心" }],
            removed: [{ type: "permission", key: "invoice.delete", name: "删除发票" }],
          },
        });
      }
      if (url === "/console/api/v1/apps/demo/permission-template-versions?page=1&page_size=20" && !init?.method) {
        return versionsResponse();
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    await user.click(screen.getByLabelText("Manifest 内容"));
    await user.paste('{"permissions":[{"key":"invoice.approve"}]}');
    await user.click(screen.getByRole("button", { name: "预览差异" }));

    expect(await screen.findByText("新增")).toBeInTheDocument();
    expect(screen.getByText("permission:invoice.approve")).toBeInTheDocument();
    expect(screen.getByText("变更")).toBeInTheDocument();
    expect(screen.getByText("group:finance")).toBeInTheDocument();
    expect(screen.getByText("移除")).toBeInTheDocument();
    expect(screen.getByText("permission:invoice.delete")).toBeInTheDocument();
  });

  test("确认导入 manifest 后刷新 catalog_version", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/permission-template-imports/preview" && init?.method === "POST") {
        return jsonResponse({ preview_id: "preview-1", diff: { added: [{ type: "permission", key: "invoice.approve" }] } });
      }
      if (url === "/console/api/v1/apps/demo/permission-template-imports/preview-1/confirm" && init?.method === "POST") {
        return jsonResponse({ catalog_version: "v2" });
      }
      if (url === "/console/api/v1/apps/demo/permission-template-versions?page=1&page_size=20" && !init?.method) {
        return versionsResponse([{ version: "v2", imported_at: "2026-07-01T09:00:00Z" }], 1);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<ManifestTab appKey="demo" />);

    await user.click(screen.getByLabelText("Manifest 内容"));
    await user.paste('{"permissions":[{"key":"invoice.approve"}]}');
    await user.click(screen.getByRole("button", { name: "预览差异" }));
    await user.click(await screen.findByRole("button", { name: "确认导入" }));

    expect(await screen.findByText("当前目录版本：v2")).toBeInTheDocument();
    await waitFor(() => {
      expect(findFetchCall(fetchMock, "/console/api/v1/apps/demo/permission-template-imports/preview-1/confirm", "POST")).toBeDefined();
    });
  });

  test("联调结果结构化展示 source 和 snapshot version", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/permission-query-tests" && init?.method === "POST") {
        return jsonResponse({
          app_key: "demo",
          user_id: "alice",
          allowed: true,
          source: "live",
          snapshot_version: "snap-20260701",
          groups: [{ key: "finance", name: "财务中心", source: "direct" }],
          grants: [
            {
              permission: "invoice.approve",
              scope: "tenant",
              source_type: "group",
              source_key: "finance",
              snapshot_version: "snap-20260701",
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

    expect(await screen.findByText("live")).toBeInTheDocument();
    expect(screen.getAllByText("snap-20260701").length).toBeGreaterThan(0);
    expect(screen.getByRole("columnheader", { name: "授权组" })).toBeInTheDocument();
    expect(screen.getAllByText("finance").length).toBeGreaterThan(0);
    expect(screen.getByRole("columnheader", { name: "授权项" })).toBeInTheDocument();
    expect(screen.getByText("invoice.approve")).toBeInTheDocument();
    expect(screen.getByText("tenant")).toBeInTheDocument();
    expect(screen.getByText("group:finance")).toBeInTheDocument();
  });

  test("审批规则支持新建、编辑、启停 direct permission 规则", async () => {
    let rules = [
      { id: 1, target_type: "authorization_group", target_key: "finance", approver_userids: ["leader"], is_active: true },
      {
        id: 2,
        target_type: "permission",
        target_key: "invoice.approve",
        approver_userids: ["security"],
        is_active: false,
        blocking: true,
      },
    ];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/approval-rules" && !init?.method) {
        return jsonResponse({ data: rules });
      }
      if (url.startsWith("/console/api/v1/user-options?")) {
        return jsonResponse({ data: [{ user_id: "local-admin:admin", name: "本地管理员 admin" }] });
      }
      if (url === "/console/api/v1/apps/demo/approval-rules" && init?.method === "POST") {
        rules = [
          ...rules,
          { id: 3, target_type: "permission", target_key: "invoice.pay", approver_userids: ["local-admin:admin"], is_active: true },
        ];
        return jsonResponse({ id: 3 });
      }
      if (url === "/console/api/v1/apps/demo/approval-rules/2" && init?.method === "PATCH") {
        const body = parseJsonBody(init);
        if ("is_active" in body && !("target_key" in body)) {
          expect(body).toEqual({ is_active: true });
          rules = rules.map((rule) => (rule.id === 2 ? { ...rule, is_active: true, blocking: false } : rule));
          return jsonResponse({ ok: true });
        }
        rules = rules.map((rule) =>
          rule.id === 2 ? { ...rule, target_key: "invoice.approve.high", approver_userids: ["local-admin:admin"] } : rule,
        );
        return jsonResponse({ ok: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<RulesTab appKey="demo" />);

    expect(await screen.findByText("授权组：finance")).toBeInTheDocument();
    expect(screen.getByText("权限：invoice.approve")).toBeInTheDocument();
    expect(screen.getByText("阻塞")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: "审批规则" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "新建" }));
    let dialog = await screen.findByRole("dialog", { name: "新建审批规则" });
    await user.selectOptions(within(dialog).getByLabelText("规则目标类型"), "permission");
    await user.type(within(dialog).getByLabelText("目标 Key"), "invoice.pay");
    await user.type(within(dialog).getByLabelText("审批人 user_id"), "admin");
    await user.click(await screen.findByRole("option", { name: /本地管理员 admin/ }));
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/user-options?q=admin&purpose=approver",
      expect.objectContaining({ credentials: "include" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "保存" }));
    expect(await screen.findByText("权限：invoice.pay")).toBeInTheDocument();

    const blockedRow = screen.getByText("权限：invoice.approve").closest("tr");
    expect(blockedRow).not.toBeNull();
    await user.click(within(blockedRow as HTMLTableRowElement).getByRole("button", { name: "编辑" }));
    dialog = await screen.findByRole("dialog", { name: "编辑审批规则" });
    await user.clear(within(dialog).getByLabelText("目标 Key"));
    await user.type(within(dialog).getByLabelText("目标 Key"), "invoice.approve.high");
    await user.click(within(dialog).getByRole("button", { name: "移除 security" }));
    await user.type(within(dialog).getByLabelText("审批人 user_id"), "admin");
    await user.click(await screen.findByRole("option", { name: /本地管理员 admin/ }));
    await user.click(within(dialog).getByRole("button", { name: "保存" }));
    expect(await screen.findByText("权限：invoice.approve.high")).toBeInTheDocument();

    const editedRow = screen.getByText("权限：invoice.approve.high").closest("tr");
    expect(editedRow).not.toBeNull();
    await user.click(within(editedRow as HTMLTableRowElement).getByRole("button", { name: "启用" }));
    await waitFor(() => {
      expect(fetchMock.mock.calls).toContainEqual([
        "/console/api/v1/apps/demo/approval-rules/2",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ is_active: true }),
        }),
      ]);
    });
  });
  test("总览页可编辑基本信息并提交 PATCH", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo" && !init?.method) {
        return jsonResponse({
          app: {
            ...appPayload.app,
            is_active: true,
            can_manage: true,
          },
        });
      }
      if (url === "/console/api/v1/apps/demo/configuration-status" && !init?.method) {
        return jsonResponse({ status: "ready", data: [] });
      }
      if (url === "/console/api/v1/apps/demo/memberships" && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === "/console/api/v1/apps/demo" && init?.method === "PATCH") {
        return jsonResponse({
          app: {
            ...appPayload.app,
            name: "Demo Renamed",
            description: "Updated description",
            is_active: false,
            can_manage: true,
          },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo");

    expect(await screen.findByRole("heading", { name: "基本信息" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑基本信息" });
    expect(within(dialog).queryByLabelText("启用应用")).not.toBeInTheDocument();
    const nameInput = within(dialog).getByLabelText("名称");
    await user.clear(nameInput);
    await user.type(nameInput, "Demo Renamed");
    const descriptionInput = within(dialog).getByLabelText("描述");
    await user.clear(descriptionInput);
    await user.type(descriptionInput, "Updated description");
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        name: "Demo Renamed",
        description: "Updated description",
      });
    });
  });

  test("总览页支持成员查看、新增和停用", async () => {
    document.body.dataset.currentUserRole = "EasyAuth Admins";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse({ app: { ...appPayload.app, can_manage: true } });
      }
      if (url === "/console/api/v1/apps/demo/configuration-status") {
        return jsonResponse({ status: "ready", data: [] });
      }
      if (url === "/console/api/v1/apps/demo/memberships" && !init?.method) {
        return jsonResponse({
          data: [
            { id: 11, user_id: "owner-a", role: "owner", is_active: true },
            { id: 22, user_id: "dev-a", role: "developer", is_active: true },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/memberships" && init?.method === "POST") {
        return jsonResponse({ membership: { id: 33, user_id: "dev-b", role: "developer", is_active: true } });
      }
      if (url === "/console/api/v1/apps/demo/memberships/22" && init?.method === "PATCH") {
        return jsonResponse({ membership: { id: 22, user_id: "dev-a", role: "developer", is_active: false } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo");

    await waitFor(() => expect(screen.getByText("owner-a")).toBeInTheDocument());
    expect(screen.getByText("dev-a")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "新建" }));
    const dialog = await screen.findByRole("dialog", { name: "新建成员" });
    await user.type(within(dialog).getByLabelText("成员用户 ID"), "dev-b");
    await user.selectOptions(within(dialog).getByLabelText("成员角色"), "developer");
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const postCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/memberships", "POST");
      expect(parseJsonBody(postCall?.[1])).toEqual({ user_id: "dev-b", role: "developer" });
    });

    const developerRow = screen.getByText("dev-a").closest("tr");
    expect(developerRow).not.toBeNull();
    await user.click(within(developerRow as HTMLTableRowElement).getByRole("button", { name: "停用" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/memberships/22", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({ is_active: false });
    });
  });
});

function renderWorkspace(initialEntry: string) {
  renderWithClient(
    <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
        <Route
          path="/console/apps/:appKey"
          element={
            <>
              <Suspense fallback={null}>
                <LazyConsoleAppWorkspace />
              </Suspense>
              <LocationProbe />
              <WorkspaceNavigationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function WorkspaceNavigationProbe() {
  const navigate = useNavigate();
  return <button type="button" onClick={() => navigate("/console/apps/second?tab=test")}>导航到第二个应用</button>;
}

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
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

function findFetchCall(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, url: string, method: string) {
  return fetchMock.mock.calls.find(([input, init]) => String(input) === url && init?.method === method);
}

function parseJsonBody(init: RequestInit | undefined) {
  return JSON.parse(String(init?.body));
}

function versionsResponse(data: unknown[] = [], totalItems = data.length) {
  return jsonResponse({
    data,
    pagination: { page: 1, page_size: 20, total_items: totalItems, total_pages: totalItems === 0 ? 0 : 1 },
  });
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
