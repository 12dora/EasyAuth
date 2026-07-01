import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsoleAppWorkspace } from "./ConsoleAppWorkspace";

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
  });

  test("矩阵保存时提交变更后的 assignments 和 base_version", async () => {
    const matrixPayload = {
      version: "v1",
      roles: [{ id: 10, key: "admin", name: "管理员" }],
      permissions: [{ id: 20, key: "invoice.read", name: "发票读取" }],
      cells: [{ role_id: 10, permission_id: 20, enabled: false }],
    };
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo") {
        return jsonResponse(appPayload);
      }
      if (url === "/console/api/v1/apps/demo/role-permission-matrix" && !init?.method) {
        return jsonResponse(matrixPayload);
      }
      if (url === "/console/api/v1/apps/demo/role-permission-matrix" && init?.method === "PATCH") {
        return jsonResponse(matrixPayload);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWorkspace("/console/apps/demo?tab=matrix");

    await user.click(await screen.findByRole("checkbox", { name: "admin invoice.read" }));
    await user.click(screen.getByRole("button", { name: "保存变更" }));

    await waitFor(() => {
      const patchCall = findFetchCall(fetchMock, "/console/api/v1/apps/demo/role-permission-matrix", "PATCH");
      expect(parseJsonBody(patchCall?.[1])).toEqual({
        base_version: "v1",
        assignments: [{ role_id: 10, permission_id: 20, enabled: true }],
        add: [],
        remove: [],
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
});

function renderWorkspace(initialEntry: string) {
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
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/console/apps/:appKey" element={<ConsoleAppWorkspace />} />
        </Routes>
      </MemoryRouter>
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
