import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { lazy, Suspense, type ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

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
          items: [{ id: 10, key: "finance", name: "财务权限", description: "财务域", display_order: 10, is_active: true }],
        });
      }
      if (url === "/console/api/v1/apps/demo/permissions") {
        return jsonResponse({
          items: [
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
          items: [
            { key: "SELF", name: "本人", description: "仅本人数据", is_active: true, display_order: 1 },
            { key: "TEAM", name: "团队", description: "团队数据", is_active: false, display_order: 2 },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWorkspace("/console/apps/demo?tab=catalog");

    await screen.findByRole("heading", { name: "新增 Scope" });
    await screen.findByText("SELF");
    expect(screen.getByText("团队")).toBeInTheDocument();
    expect(screen.getAllByText("停用").length).toBeGreaterThan(0);
    expect(screen.getAllByText("finance").length).toBeGreaterThan(0);
    expect(screen.getByText("财务权限")).toBeInTheDocument();
    expect(screen.getByText("invoice.read")).toBeInTheDocument();
    expect(screen.getByText("SELF、TEAM")).toBeInTheDocument();
    expect(screen.getAllByText("high").length).toBeGreaterThan(0);
  });

  test("授权组保存 payload 包含 permission 和 scope", async () => {
    const authorizationGroupsPayload = {
      version: "catalog-v1",
      items: [
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
          items: [
            { id: 20, key: "invoice.read", name: "发票读取", supported_scopes: ["SELF", "TEAM"], risk_level: "standard" },
            { id: 21, key: "invoice.export", name: "发票导出", supported_scopes: ["TEAM"], risk_level: "high" },
          ],
        });
      }
      if (url === "/console/api/v1/apps/demo/scopes") {
        return jsonResponse({
          items: [
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
    expect(screen.getAllByText("role").length).toBeGreaterThan(0);
    expect(screen.getAllByText("invoice.read / SELF").length).toBeGreaterThan(0);

    await user.selectOptions(screen.getByLabelText("Grant Permission"), "invoice.export");
    await user.selectOptions(screen.getByLabelText("Grant Scope"), "TEAM");
    await user.click(screen.getByRole("button", { name: "添加 Grant" }));
    await user.click(screen.getByRole("button", { name: "保存授权组" }));

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
        return jsonResponse({ items: [] });
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

    await user.type(await screen.findByLabelText("凭据名称"), "primary token");
    await user.click(screen.getByRole("button", { name: "静态 token" }));

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
          items: [
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
      if (url === "/console/api/v1/apps/demo/permission-template-versions" && !init?.method) {
        return jsonResponse({ items: [] });
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
      if (url === "/console/api/v1/apps/demo/permission-template-versions" && !init?.method) {
        return jsonResponse({ items: [{ version: "v2", imported_at: "2026-07-01T09:00:00Z" }] });
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

    expect(await screen.findByText("来源：live")).toBeInTheDocument();
    expect(screen.getByText("快照版本：snap-20260701")).toBeInTheDocument();
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
        return jsonResponse({ items: rules });
      }
      if (url === "/console/api/v1/apps/demo/approval-rules" && init?.method === "POST") {
        rules = [
          ...rules,
          { id: 3, target_type: "permission", target_key: "invoice.pay", approver_userids: ["owner"], is_active: true },
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
          rule.id === 2 ? { ...rule, target_key: "invoice.approve.high", approver_userids: ["security", "owner"] } : rule,
        );
        return jsonResponse({ ok: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<RulesTab appKey="demo" />);

    expect(await screen.findByText("authorization_group:finance")).toBeInTheDocument();
    expect(screen.getByText("permission:invoice.approve")).toBeInTheDocument();
    expect(screen.getByText("Blocking")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("规则目标类型"), "permission");
    await user.type(screen.getByLabelText("目标 Key"), "invoice.pay");
    await user.type(screen.getByLabelText("审批人 userids"), "owner");
    await user.click(screen.getByRole("button", { name: "新建规则" }));
    expect(await screen.findByText("permission:invoice.pay")).toBeInTheDocument();

    const blockedRow = screen.getByText("permission:invoice.approve").closest("tr");
    expect(blockedRow).not.toBeNull();
    await user.click(within(blockedRow as HTMLTableRowElement).getByRole("button", { name: "编辑" }));
    await user.clear(screen.getByLabelText("目标 Key"));
    await user.type(screen.getByLabelText("目标 Key"), "invoice.approve.high");
    await user.clear(screen.getByLabelText("审批人 userids"));
    await user.type(screen.getByLabelText("审批人 userids"), "security,owner");
    await user.click(screen.getByRole("button", { name: "保存规则" }));
    expect(await screen.findByText("permission:invoice.approve.high")).toBeInTheDocument();

    const editedRow = screen.getByText("permission:invoice.approve.high").closest("tr");
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
        return jsonResponse({ status: "ready", issues: [] });
      }
      if (url === "/console/api/v1/apps/demo/memberships" && !init?.method) {
        return jsonResponse({ items: [] });
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

    await user.click(await screen.findByRole("button", { name: "编辑基本信息" }));
    const nameInput = screen.getByLabelText("名称");
    await user.clear(nameInput);
    await user.type(nameInput, "Demo Renamed");
    const descriptionInput = screen.getByLabelText("描述");
    await user.clear(descriptionInput);
    await user.type(descriptionInput, "Updated description");
    await user.click(screen.getByLabelText("启用应用"));
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        name: "Demo Renamed",
        description: "Updated description",
        is_active: false,
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
        return jsonResponse({ status: "ready", issues: [] });
      }
      if (url === "/console/api/v1/apps/demo/memberships" && !init?.method) {
        return jsonResponse({
          items: [
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

    await user.type(screen.getByLabelText("成员用户 ID"), "dev-b");
    await user.selectOptions(screen.getByLabelText("成员角色"), "developer");
    await user.click(screen.getByRole("button", { name: "新增成员" }));

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
            <Suspense fallback={null}>
              <LazyConsoleAppWorkspace />
            </Suspense>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
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
      {ui}
    </QueryClientProvider>,
  );
}

function findFetchCall(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, url: string, method: string) {
  return fetchMock.mock.calls.find(([input, init]) => String(input) === url && init?.method === method);
}

function parseJsonBody(init: RequestInit | undefined) {
  return JSON.parse(String(init?.body));
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
