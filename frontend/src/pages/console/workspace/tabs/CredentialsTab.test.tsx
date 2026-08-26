import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { AppConfigProvider } from "../../../../components/antd/AppConfigProvider";
import { CredentialsTab } from "./CredentialsTab";

// antd Table 每次筛选都要重建整棵表格, jsdom 下比自研原语慢;
// 整套测试并行跑时表头筛选用例会逼近 20s, 因此本文件放宽到 30s。
vi.setConfig({ testTimeout: 30000 });

describe("CredentialsTab(FF-4)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("创建请求在途时重复点击只发出一次 POST", async () => {
    const createUrl = "/console/api/v1/apps/demo/credentials/static-tokens";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === createUrl && init?.method === "POST") {
        // 让创建请求保持在途, 从而 isCreating 维持为真, 按钮禁用。
        return new Promise<Response>(() => {});
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<CredentialsTab appKey="demo" canManage />);

    await user.click(await screen.findByRole("button", { name: "新建" }));
    await user.type(screen.getByLabelText("凭据名称"), "生产凭据");

    const staticTokenButton = screen.getByRole("button", { name: /静态 token/ });
    await user.click(staticTokenButton);
    expect(staticTokenButton).toBeDisabled();
    await user.click(staticTokenButton);

    const postCalls = fetchMock.mock.calls.filter(
      ([input, init]) => String(input) === createUrl && init?.method === "POST",
    );
    expect(postCalls).toHaveLength(1);
  });

  test("同类型同 ID 的轮换和禁用串行执行，不同类型同 ID 互不阻塞，且轮换明文不会被覆盖", async () => {
    const rotateUrl7 = "/console/api/v1/apps/demo/credentials/static-tokens/7/rotate";
    const rotateUrl8 = "/console/api/v1/apps/demo/credentials/static-tokens/8/rotate";
    const disableUrl7 = "/console/api/v1/apps/demo/credentials/static-tokens/7/disable";
    const disableOauthUrl7 = "/console/api/v1/apps/demo/credentials/oauth-clients/7/disable";
    let resolveRotate7!: (response: Response) => void;
    let resolveRotate8!: (response: Response) => void;
    const rotate7Response = new Promise<Response>((resolve) => {
      resolveRotate7 = resolve;
    });
    const rotate8Response = new Promise<Response>((resolve) => {
      resolveRotate8 = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({
          data: [
            { id: 7, kind: "static_token", name: "生产凭据", is_active: true },
            { id: 7, kind: "oauth_client", name: "生产 OAuth", is_active: true, client_id: "client-7" },
            { id: 8, kind: "static_token", name: "备用凭据", is_active: true },
          ],
        });
      }
      if (url === rotateUrl7 && init?.method === "POST") {
        return rotate7Response;
      }
      if (url === rotateUrl8 && init?.method === "POST") {
        return rotate8Response;
      }
      if (url === disableOauthUrl7 && init?.method === "POST") {
        return jsonResponse({ ok: true });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<CredentialsTab appKey="demo" canManage />);

    const row7 = (await screen.findByText("生产凭据")).closest("tr");
    expect(row7).not.toBeNull();
    const rotate7 = within(row7 as HTMLTableRowElement).getByRole("button", { name: "轮换" });

    await user.click(rotate7);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === rotateUrl7)).toHaveLength(1);
    let pendingRow7: HTMLTableRowElement | null = null;
    await waitFor(() => {
      pendingRow7 = screen.getByText("生产凭据").closest("tr");
      expect(pendingRow7).not.toBeNull();
      expect(within(pendingRow7 as HTMLTableRowElement).getByRole("button", { name: "轮换" })).toBeDisabled();
      expect(within(pendingRow7 as HTMLTableRowElement).getByRole("button", { name: "禁用" })).toBeDisabled();
    });
    await user.click(within(pendingRow7!).getByRole("button", { name: "轮换" }));
    await user.click(within(pendingRow7!).getByRole("button", { name: "禁用" }));
    const oauthRow7 = screen.getByText("生产 OAuth").closest("tr");
    expect(oauthRow7).not.toBeNull();
    const disableOauth7 = within(oauthRow7 as HTMLTableRowElement).getByRole("button", { name: "禁用" });
    expect(disableOauth7).toBeEnabled();
    await user.click(disableOauth7);
    const currentRow8 = screen.getByText("备用凭据").closest("tr");
    expect(currentRow8).not.toBeNull();
    await user.click(within(currentRow8 as HTMLTableRowElement).getByRole("button", { name: "轮换" }));

    expect(fetchMock.mock.calls.filter(([input]) => String(input) === rotateUrl7)).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === disableUrl7)).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === disableOauthUrl7)).toHaveLength(1);

    resolveRotate7(jsonResponse({ one_time_secret: { kind: "static_token", app_token: "token-7-once" } }));
    expect(await screen.findByText("token-7-once")).toBeVisible();
    resolveRotate8(jsonResponse({ one_time_secret: { kind: "static_token", app_token: "token-8-once" } }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input) === rotateUrl8)).toHaveLength(1));

    await user.click(screen.getByRole("button", { name: "关闭" }));
    expect(await screen.findByText("token-8-once")).toBeVisible();
    expect(screen.queryByText("token-7-once")).not.toBeInTheDocument();
  });

  test("创建默认最小权限凭据并通过真实 owner 端点更新 capabilities", async () => {
    const createUrl = "/console/api/v1/apps/demo/credentials/static-tokens";
    const capabilityUrl = "/console/api/v1/apps/demo/credentials/static-tokens/7/capabilities";
    const oauthCapabilityUrl = "/console/api/v1/apps/demo/credentials/oauth-clients/8/capabilities";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({
          data: [
            { id: 7, kind: "static_token", name: "生产凭据", is_active: true, capabilities: [] },
            { id: 8, kind: "oauth_client", name: "通知 OAuth", is_active: true, capabilities: ["notify"] },
          ],
        });
      }
      if (url === createUrl && init?.method === "POST") {
        return jsonResponse({ one_time_secret: { kind: "static_token", app_token: "once" } }, 201);
      }
      if (url === capabilityUrl && init?.method === "PUT") {
        return jsonResponse({
          credential: { id: 7, kind: "static_token", name: "生产凭据", is_active: true, capabilities: ["notify"] },
        });
      }
      if (url === oauthCapabilityUrl && init?.method === "PUT") {
        return jsonResponse({
          credential: { id: 8, kind: "oauth_client", name: "通知 OAuth", is_active: true, capabilities: ["directory"] },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<CredentialsTab appKey="demo" canManage />);

    await waitFor(() => expect(screen.getByText("仅权限查询")).toBeVisible());
    await user.click(screen.getByRole("button", { name: "新建" }));
    await user.type(screen.getByLabelText("凭据名称"), "目录同步凭据");
    await user.click(screen.getByRole("checkbox", { name: "directory" }));
    await user.click(screen.getByRole("button", { name: "静态 token" }));
    await waitFor(() => expect(findFetchCall(fetchMock, createUrl, "POST")).toBeDefined());
    expect(JSON.parse(String(findFetchCall(fetchMock, createUrl, "POST")?.[1]?.body))).toEqual({
      name: "目录同步凭据",
      capabilities: ["directory"],
    });
    await user.click(screen.getByRole("button", { name: "关闭" }));

    const staticRow = screen.getByText("生产凭据").closest("tr");
    expect(staticRow).not.toBeNull();
    await user.click(within(staticRow as HTMLTableRowElement).getByRole("button", { name: "编辑能力" }));
    await user.click(screen.getByRole("checkbox", { name: "notify" }));
    await user.click(screen.getByRole("button", { name: "保存能力" }));
    await waitFor(() => expect(findFetchCall(fetchMock, capabilityUrl, "PUT")).toBeDefined());
    expect(JSON.parse(String(findFetchCall(fetchMock, capabilityUrl, "PUT")?.[1]?.body))).toEqual({ capabilities: ["notify"] });

    const oauthRow = screen.getByText("通知 OAuth").closest("tr");
    expect(oauthRow).not.toBeNull();
    await user.click(within(oauthRow as HTMLTableRowElement).getByRole("button", { name: "编辑能力" }));
    await user.click(screen.getByRole("checkbox", { name: "notify" }));
    await user.click(screen.getByRole("checkbox", { name: "directory" }));
    await user.click(screen.getByRole("button", { name: "保存能力" }));
    await waitFor(() => expect(findFetchCall(fetchMock, oauthCapabilityUrl, "PUT")).toBeDefined());
    expect(JSON.parse(String(findFetchCall(fetchMock, oauthCapabilityUrl, "PUT")?.[1]?.body))).toEqual({ capabilities: ["directory"] });
  });

  test("developer 只能查看凭据能力且不能创建或修改凭据", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({
          data: [{ id: 7, kind: "static_token", name: "通知凭据", is_active: true, capabilities: ["notify"] }],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<CredentialsTab appKey="demo" canManage={false} />);

    await waitFor(() => expect(screen.getByText("notify")).toBeVisible());
    expect(screen.queryByRole("button", { name: "新建" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "编辑能力" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "禁用" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  test("凭据表头按类型和能力筛选, 并渲染 AppTable 分页", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({
          data: [
            { id: 7, kind: "static_token", name: "生产凭据", is_active: true, capabilities: [] },
            { id: 8, kind: "oauth_client", name: "通知 OAuth", is_active: true, capabilities: ["notify"], client_id: "client-8" },
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    // antd 表格每次筛选都要整表重渲染, user-event 默认的事件间隔会让本用例逼近超时。
    const user = userEvent.setup({ delay: null });

    renderWithClient(<CredentialsTab appKey="demo" canManage />);

    await screen.findByText("生产凭据");
    expect(bodyRowNames()).toEqual(["生产凭据", "通知 OAuth"]);

    const pagination = document.querySelector("ul.ant-pagination");
    expect(pagination).not.toBeNull();
    expect(pagination?.querySelector(".ant-pagination-total-text")).not.toBeNull();
    expect(pagination?.querySelector(".ant-pagination-options")).not.toBeNull();

    const kindDropdown = await openHeaderFilter(user, "类型");
    await user.click(within(kindDropdown).getByText("OAuth client"));
    await user.click(within(kindDropdown).getByRole("button", { name: "确定" }));
    await waitFor(() => expect(bodyRowNames()).toEqual(["通知 OAuth"]));

    await openHeaderFilter(user, "类型");
    await user.click(within(kindDropdown).getByText("OAuth client"));
    await user.click(within(kindDropdown).getByRole("button", { name: "确定" }));
    await waitFor(() => expect(bodyRowNames()).toHaveLength(2));

    // 没有任何能力的凭据归到「仅权限查询」这一档。
    const capabilityDropdown = await openHeaderFilter(user, "平台能力");
    await user.click(within(capabilityDropdown).getByText("仅权限查询"));
    await user.click(within(capabilityDropdown).getByRole("button", { name: "确定" }));
    await waitFor(() => expect(bodyRowNames()).toEqual(["生产凭据"]));
  });
});

function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <AppConfigProvider>{ui}</AppConfigProvider>
    </QueryClientProvider>,
  );
}

/** 打开指定表头的筛选下拉, 返回当前展开的那个下拉面板。 */
async function openHeaderFilter(user: ReturnType<typeof userEvent.setup>, headerText: string): Promise<HTMLElement> {
  const header = screen.getAllByRole("columnheader").find((cell) => cell.textContent?.includes(headerText));
  expect(header).toBeDefined();
  const trigger = (header as HTMLElement).querySelector(".ant-table-filter-trigger");
  expect(trigger).not.toBeNull();
  await user.click(trigger as HTMLElement);
  return waitFor(() => {
    const dropdown = document.querySelector(".ant-dropdown:not(.ant-dropdown-hidden) .ant-table-filter-dropdown");
    expect(dropdown).not.toBeNull();
    return dropdown as HTMLElement;
  });
}

function bodyRowNames(): string[] {
  return [...document.querySelectorAll(".ant-table-tbody tr.ant-table-row")].map(
    (row) => row.querySelector("td")?.textContent ?? "",
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function findFetchCall(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, url: string, method: string) {
  return fetchMock.mock.calls.find(([input, init]) => String(input) === url && init?.method === method);
}
