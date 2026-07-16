import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ToastProvider } from "../../../../components/ui/Toast";
import { IntegrationTab } from "./IntegrationTab";

const CAPABILITIES_URL = "/console/api/v1/apps/demo/capabilities";
const CHANNEL_URL = "/console/api/v1/apps/demo/notification-channel";

describe("IntegrationTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("系统管理员可开通平台能力，App owner 可保存通道新版本且 secret 不回显", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse({
          can_manage: true,
          capabilities: [
            { capability: "directory", enabled: false, config: {} },
            { capability: "notify", enabled: true, config: {} },
          ],
        });
      }
      if (url === `${CAPABILITIES_URL}/directory` && init?.method === "PUT") {
        return jsonResponse({ capability: { capability: "directory", enabled: true, config: {} } });
      }
      if (url === CHANNEL_URL && !init?.method) {
        return jsonResponse({
          notification_channel: {
            id: 3,
            name: "EasyTrade 通知",
            dingtalk_app_key: "ding-app-key",
            dingtalk_app_secret: "must-never-render",
            app_secret_configured: true,
            agent_id: "9001",
            directory_source_slug: "authentik-main",
            corp_id: "corp-001",
            version: 1,
            is_active: true,
          },
          available_directory_scopes: availableScopes(),
        });
      }
      if (url === CHANNEL_URL && init?.method === "PUT") {
        return jsonResponse({
          notification_channel: {
            id: 4,
            name: "EasyTrade 通知",
            dingtalk_app_key: "ding-app-key",
            app_secret_configured: true,
            agent_id: "9001",
            directory_source_slug: "authentik-secondary",
            corp_id: "corp-002",
            version: 2,
            is_active: true,
          },
        }, 201);
      }
      if (url === `${CHANNEL_URL}/test` && init?.method === "POST") {
        return jsonResponse({ ok: true, version: 2 });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    const client = renderWithClient(<IntegrationTab appKey="demo" canManage />);

    let directorySwitch!: HTMLElement;
    await waitFor(() => {
      directorySwitch = screen.getByRole("switch", { name: "切换 directory 平台能力" });
      expect(directorySwitch).toBeEnabled();
    });
    await user.click(directorySwitch);
    await waitFor(() => expect(findCall(fetchMock, `${CAPABILITIES_URL}/directory`, "PUT")).toBeDefined());
    expect(JSON.parse(String(findCall(fetchMock, `${CAPABILITIES_URL}/directory`, "PUT")?.[1]?.body))).toEqual({
      enabled: true,
      config: {},
    });

    expect(await screen.findByDisplayValue("EasyTrade 通知")).toBeVisible();
    expect(screen.queryByDisplayValue("must-never-render")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("must-never-render");
    expect(JSON.stringify(client.getQueryData(["console", "app", "demo", "notification-channel"]))).not.toContain("must-never-render");
    expect(client.getQueryData(["console", "app", "demo", "notification-channel"])).toMatchObject({
      available_directory_scopes: availableScopes(),
    });
    expect(screen.getByLabelText("钉钉 App Secret")).toHaveValue("");
    expect(screen.getByText("authentik-main / corp-001", { selector: "code" })).toBeVisible();
    await user.selectOptions(screen.getByLabelText("企业目录作用域"), JSON.stringify(["authentik-secondary", "corp-002"]));
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    await waitFor(() => expect(findCall(fetchMock, CHANNEL_URL, "PUT")).toBeDefined());
    expect(JSON.parse(String(findCall(fetchMock, CHANNEL_URL, "PUT")?.[1]?.body))).toEqual({
      name: "EasyTrade 通知",
      dingtalk_app_key: "ding-app-key",
      dingtalk_app_secret: "",
      agent_id: "9001",
      directory_source_slug: "authentik-secondary",
      corp_id: "corp-002",
    });
    await user.click(screen.getByRole("button", { name: "测试连通性" }));
    await waitFor(() => expect(findCall(fetchMock, `${CHANNEL_URL}/test`, "POST")).toBeDefined());
  });

  test("普通 App owner 不能开平台能力，但可以配置未创建的通知通道", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse({
          can_manage: false,
          capabilities: [
            { capability: "directory", enabled: false, config: {} },
            { capability: "notify", enabled: false, config: {} },
          ],
        });
      }
      if (url === CHANNEL_URL && !init?.method) {
        return jsonResponse({ notification_channel: null, available_directory_scopes: availableScopes() });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

    expect(await screen.findByText("需系统管理员开通")).toBeVisible();
    expect(screen.getByRole("switch", { name: "切换 directory 平台能力" })).toBeDisabled();
    await waitFor(() => expect(screen.getByText("未配置", { selector: "strong" })).toBeVisible());
    expect(screen.getByLabelText("通道名称")).toBeEnabled();
    expect(screen.getByLabelText("企业目录作用域")).toBeEnabled();
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });

  test("developer 对通知通道只读", async () => {
    vi.stubGlobal("fetch", readOnlyFetch());

    renderWithClient(<IntegrationTab appKey="demo" canManage={false} />);

    await waitFor(() => expect(screen.getByLabelText("通道名称")).toBeDisabled());
    expect(screen.getByLabelText("企业目录作用域")).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
  });

  test("首次配置必须填写 secret，填写后 PUT 明文仅进入请求体并立即清空", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse(capabilitiesPayload(false));
      }
      if (url === CHANNEL_URL && !init?.method) {
        return jsonResponse({ notification_channel: null, available_directory_scopes: availableScopes() });
      }
      if (url === CHANNEL_URL && init?.method === "PUT") {
        return jsonResponse({ notification_channel: channelPayload(1) }, 201);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

    const nameInput = await screen.findByLabelText("通道名称");
    await waitFor(() => expect(nameInput).toBeEnabled());
    await user.type(nameInput, "EasyTrade 通知");
    await user.type(screen.getByLabelText("Agent ID"), "9001");
    await user.type(screen.getByLabelText("钉钉 App Key"), "ding-app-key");
    await user.selectOptions(screen.getByLabelText("企业目录作用域"), JSON.stringify(["authentik-main", "corp-001"]));
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
    const secretInput = screen.getByLabelText("钉钉 App Secret");
    await user.type(secretInput, "one-time-secret");
    const saveButton = screen.getByRole("button", { name: "保存新版本" });
    expect(saveButton).toBeEnabled();
    await user.click(saveButton);

    await waitFor(() => expect(findCall(fetchMock, CHANNEL_URL, "PUT")).toBeDefined());
    expect(JSON.parse(String(findCall(fetchMock, CHANNEL_URL, "PUT")?.[1]?.body))).toEqual({
      name: "EasyTrade 通知",
      dingtalk_app_key: "ding-app-key",
      dingtalk_app_secret: "one-time-secret",
      agent_id: "9001",
      directory_source_slug: "authentik-main",
      corp_id: "corp-001",
    });
    await waitFor(() => expect(secretInput).toHaveValue(""));
  });

  test("loading/error/unconfigured/configured 状态不混淆，GET 失败时禁写并可重试", async () => {
    let rejectChannel!: (reason: Error) => void;
    const channelResponse = new Promise<Response>((_resolve, reject) => {
      rejectChannel = reject;
    });
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse(capabilitiesPayload(false));
      }
      if (url === CHANNEL_URL && !init?.method) {
        return channelResponse;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

    expect(await screen.findByText("正在加载通知通道")).toBeVisible();
    expect(screen.queryByText("未配置", { selector: "strong" })).not.toBeInTheDocument();
    rejectChannel(new Error("network down"));
    expect(await screen.findByText("通知通道加载失败", { selector: "strong" })).toBeVisible();
    expect(screen.getByLabelText("通道名称")).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeEnabled();
    expect(screen.queryByText("未配置", { selector: "strong" })).not.toBeInTheDocument();
  });

  test("保存与连通性失败显示 toast，secret 在失败后也立即清空", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse(capabilitiesPayload(false));
      }
      if (url === CHANNEL_URL && !init?.method) {
        return jsonResponse({ notification_channel: channelPayload(1), available_directory_scopes: availableScopes() });
      }
      if (url === CHANNEL_URL && init?.method === "PUT") {
        return jsonResponse({ error: { code: "validation_error", message: "save rejected" } }, 422);
      }
      if (url === `${CHANNEL_URL}/test` && init?.method === "POST") {
        return jsonResponse({ error: { code: "dependency_unavailable", message: "test rejected" } }, 503);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

    const secretInput = await screen.findByLabelText("钉钉 App Secret");
    await user.type(secretInput, "replacement-secret");
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    expect(await screen.findByText("通知通道保存失败")).toBeVisible();
    expect(secretInput).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "测试连通性" }));
    expect(await screen.findByText("通知通道连通性测试失败")).toBeVisible();
  });

  test("当前 scope 已消失时告警且不能提交，owner 选择有效 scope 后可修复", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse(capabilitiesPayload(false));
      }
      if (url === CHANNEL_URL && !init?.method) {
        return jsonResponse({
          notification_channel: channelPayload(1),
          available_directory_scopes: [{ directory_source_slug: "authentik-secondary", corp_id: "corp-002" }],
        });
      }
      if (url === CHANNEL_URL && init?.method === "PUT") {
        return jsonResponse({
          notification_channel: {
            ...channelPayload(2),
            directory_source_slug: "authentik-secondary",
            corp_id: "corp-002",
          },
        }, 201);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

    expect(await screen.findByText("当前企业目录作用域已失效")).toBeVisible();
    const scopeSelect = screen.getByLabelText("企业目录作用域");
    expect(scopeSelect).toHaveValue(JSON.stringify(["authentik-main", "corp-001"]));
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
    await user.selectOptions(scopeSelect, JSON.stringify(["authentik-secondary", "corp-002"]));
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    await waitFor(() => expect(findCall(fetchMock, CHANNEL_URL, "PUT")).toBeDefined());
    expect(JSON.parse(String(findCall(fetchMock, CHANNEL_URL, "PUT")?.[1]?.body))).toMatchObject({
      directory_source_slug: "authentik-secondary",
      corp_id: "corp-002",
    });
  });

  test("available scope 为空时明确阻止 owner 创建通道", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === CAPABILITIES_URL && !init?.method) {
        return jsonResponse(capabilitiesPayload(false));
      }
      if (url === CHANNEL_URL && !init?.method) {
        return jsonResponse({ notification_channel: null, available_directory_scopes: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

    expect(await screen.findByText("暂无可用企业目录作用域")).toBeVisible();
    expect(screen.getByLabelText("企业目录作用域")).toBeDisabled();
    expect(screen.getByRole("button", { name: "保存新版本" })).toBeDisabled();
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method)).toBe(true);
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
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
  return client;
}

function capabilitiesPayload(canManage: boolean) {
  return {
    can_manage: canManage,
    capabilities: [
      { capability: "directory", enabled: false, config: {} },
      { capability: "notify", enabled: false, config: {} },
    ],
  };
}

function channelPayload(version: number) {
  return {
    id: version,
    name: "EasyTrade 通知",
    dingtalk_app_key: "ding-app-key",
    app_secret_configured: true,
    agent_id: "9001",
    directory_source_slug: "authentik-main",
    corp_id: "corp-001",
    version,
    is_active: true,
  };
}

function availableScopes() {
  return [
    { directory_source_slug: "authentik-main", corp_id: "corp-001" },
    { directory_source_slug: "authentik-secondary", corp_id: "corp-002" },
  ];
}

function readOnlyFetch() {
  return vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === CAPABILITIES_URL && !init?.method) {
      return jsonResponse(capabilitiesPayload(false));
    }
    if (url === CHANNEL_URL && !init?.method) {
      return jsonResponse({ notification_channel: channelPayload(1), available_directory_scopes: availableScopes() });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function findCall(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, url: string, method: string) {
  return fetchMock.mock.calls.find(([input, init]) => String(input) === url && init?.method === method);
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
