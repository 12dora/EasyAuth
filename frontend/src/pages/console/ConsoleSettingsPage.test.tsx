import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ConsoleSettingsPage } from "./ConsoleSettingsPage";

const SETTINGS_URL = "/console/api/v1/settings/integrations";
const TWO_FACTOR_URL = "/console/api/v1/security/two-factor";

const SETTINGS = {
  authentik_base_url_override: "https://auth.example.com",
  authentik_base_url_effective: "https://auth.example.com",
  authentik_base_url_source: "override",
  authentik_api_token_configured: true,
  authentik_api_token_source: "override",
  authentik_source_slug: "dingtalk",
  dingtalk_app_key: "old-key",
  dingtalk_app_secret_configured: true,
  dingtalk_agent_id: "1001",
  dingtalk_notify_app_key: "",
  dingtalk_notify_app_secret_configured: false,
  dingtalk_notify_agent_id: "",
  dingtalk_notify_work_notice_enabled: true,
  dingtalk_notify_robot_enabled: true,
  updated_at: "2026-07-10T08:00:00Z",
  updated_by: "admin",
};

describe("ConsoleSettingsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("保存钉钉字段时不发送 Authentik 配置", async () => {
    const fetchMock = settingsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const dingtalkForm = (await screen.findByLabelText("钉钉 AppKey")).closest("form");
    expect(dingtalkForm).not.toBeNull();
    const appKeyInput = within(dingtalkForm!).getByLabelText("钉钉 AppKey");
    await waitFor(() => expect(appKeyInput).toHaveValue("old-key"));
    fireEvent.change(appKeyInput, { target: { value: "new-key" } });
    await user.click(within(dingtalkForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ dingtalk_app_key: "new-key" });
    });
  });

  test("保存 Authentik token 时只发送实际修改的字段", async () => {
    const fetchMock = settingsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const authentikForm = (await screen.findByLabelText(/API Token/)).closest("form");
    expect(authentikForm).not.toBeNull();
    await user.type(within(authentikForm!).getByLabelText(/API Token/), "new-token");
    await user.click(within(authentikForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ authentik_api_token: "new-token" });
    });
  });

  test("清空 Authentik URL 时发送显式空字符串", async () => {
    const fetchMock = settingsFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const authentikForm = (await screen.findByLabelText(/Authentik Base URL/)).closest("form");
    expect(authentikForm).not.toBeNull();
    const baseUrlInput = within(authentikForm!).getByLabelText(/Authentik Base URL/);
    await waitFor(() => expect(baseUrlInput).toHaveValue("https://auth.example.com"));
    await user.clear(baseUrlInput);
    await user.click(within(authentikForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ authentik_base_url: "" });
    });
  });

  test("服务号卡片可单独保存且不回显 secret", async () => {
    const fetchMock = settingsFetchMock({
      dingtalk_notify_app_key: "svc-key",
      dingtalk_notify_app_secret_configured: true,
      dingtalk_notify_agent_id: "9001",
      dingtalk_notify_app_secret: "must-never-render",
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    expect(await screen.findByRole("heading", { name: "钉钉 · 服务号" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "钉钉 · 统一认证应用" })).toBeVisible();
    const notifyKey = await screen.findByLabelText("服务号 AppKey");
    await waitFor(() => expect(notifyKey).toHaveValue("svc-key"));
    const notifyForm = notifyKey.closest("form");
    expect(notifyForm).not.toBeNull();
    expect(within(notifyForm!).getAllByText("已设置")).toHaveLength(1);
    expect(screen.getByLabelText("服务号 AppSecret")).toHaveValue("");
    expect(document.body).not.toHaveTextContent("must-never-render");
    fireEvent.change(notifyKey, { target: { value: "svc-key-2" } });
    await user.type(screen.getByLabelText("服务号 AppSecret"), "one-time-notify-secret");
    await user.click(within(notifyForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({
        dingtalk_notify_app_key: "svc-key-2",
        dingtalk_notify_app_secret: "one-time-notify-secret",
      });
    });
    expect(JSON.stringify(requestBody(fetchMock))).not.toContain("must-never-render");
  });

  test("统一认证应用卡片的保存不携带服务号字段", async () => {
    const fetchMock = settingsFetchMock({ dingtalk_notify_app_key: "svc-key" });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const agentId = await screen.findByLabelText("钉钉 AgentId");
    await waitFor(() => expect(agentId).toHaveValue("1001"));
    const appForm = agentId.closest("form");
    expect(appForm).not.toBeNull();
    expect(within(appForm!).queryByLabelText("服务号 AppKey")).toBeNull();
    fireEvent.change(agentId, { target: { value: "1002" } });
    await user.click(within(appForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ dingtalk_agent_id: "1002" });
    });
  });

  test("关闭服务号机器人开关时只发送该布尔字段", async () => {
    const fetchMock = settingsFetchMock({ dingtalk_notify_robot_enabled: true });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const toggle = await screen.findByRole("switch", { name: "服务号机器人" });
    await waitFor(() => expect(toggle).toBeChecked());
    await user.click(toggle);
    expect(toggle).not.toBeChecked();
    const notifyForm = toggle.closest("form");
    expect(notifyForm).not.toBeNull();
    await user.click(within(notifyForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ dingtalk_notify_robot_enabled: false });
    });
  });

  test("关闭工作通知开关时只发送该布尔字段", async () => {
    const fetchMock = settingsFetchMock({ dingtalk_notify_work_notice_enabled: true });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const toggle = await screen.findByRole("switch", { name: "工作通知" });
    await waitFor(() => expect(toggle).toBeChecked());
    await user.click(toggle);
    const notifyForm = toggle.closest("form");
    expect(notifyForm).not.toBeNull();
    await user.click(within(notifyForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ dingtalk_notify_work_notice_enabled: false });
    });
  });

  test("Base URL 预填环境变量回退值, 且只保存 token 时不把回退固化成覆盖值", async () => {
    const fetchMock = settingsFetchMock({
      authentik_base_url_override: "",
      authentik_base_url_effective: "https://env.example.com",
      authentik_base_url_source: "env",
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const baseUrlInput = await screen.findByLabelText(/Authentik Base URL/);
    await waitFor(() => expect(baseUrlInput).toHaveValue("https://env.example.com"));
    // 来源提示留在输入框下方, 不再有单独的「当前生效地址」尾行。
    expect(screen.getByText("当前值来自环境变量；留空则回退到环境变量配置。")).toBeVisible();
    expect(screen.queryByText("当前生效地址")).toBeNull();

    const authentikForm = baseUrlInput.closest("form");
    await user.type(within(authentikForm!).getByLabelText(/API Token/), "new-token");
    await user.click(within(authentikForm!).getByRole("button", { name: "保存设置" }));

    await waitFor(() => {
      expect(requestBody(fetchMock)).toEqual({ authentik_api_token: "new-token" });
    });
  });

  test("Authentik 测试连接成功后就地显示耗时", async () => {
    const fetchMock = settingsFetchMock(
      {},
      { [`${SETTINGS_URL}/authentik/test`]: okResult(42) },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const authentikForm = (await screen.findByLabelText(/Authentik Base URL/)).closest("form");
    await user.click(within(authentikForm!).getByRole("button", { name: "测试连接" }));

    await waitFor(() => {
      expect(within(authentikForm!).getByRole("status")).toHaveTextContent("连接正常 · 42 ms");
    });
    // 未保存的草稿值随请求一起提交, 测的是"保存后会生效的那组配置"。
    expect(testRequestBody(fetchMock, `${SETTINGS_URL}/authentik/test`)).toEqual({
      authentik_base_url: "https://auth.example.com",
      authentik_api_token: "",
    });
  });

  test("服务号测试连接失败时展示后端给出的原因", async () => {
    const fetchMock = settingsFetchMock(
      { dingtalk_notify_app_key: "svc-key", dingtalk_notify_agent_id: "9001" },
      {
        [`${SETTINGS_URL}/dingtalk-notify/test`]: {
          ok: false,
          latency_ms: 137,
          error_code: "REJECTED",
          error_message: "钉钉 oapi 业务错误: invalid appsecret",
        },
      },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const notifyForm = (await screen.findByLabelText("服务号 AppKey")).closest("form");
    await user.click(within(notifyForm!).getByRole("button", { name: "测试连接" }));

    await waitFor(() => {
      expect(within(notifyForm!).getByRole("status")).toHaveTextContent(
        "连接失败：钉钉 oapi 业务错误: invalid appsecret",
      );
    });
    expect(testRequestBody(fetchMock, `${SETTINGS_URL}/dingtalk-notify/test`)).toEqual({
      dingtalk_notify_app_key: "svc-key",
      dingtalk_notify_app_secret: "",
      dingtalk_notify_agent_id: "9001",
    });
  });

  test("统一认证应用卡片的测试连接带上未保存的三元组", async () => {
    const fetchMock = settingsFetchMock(
      {},
      { [`${SETTINGS_URL}/dingtalk/test`]: okResult(7) },
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSettings();

    const appKeyInput = await screen.findByLabelText("钉钉 AppKey");
    await waitFor(() => expect(appKeyInput).toHaveValue("old-key"));
    fireEvent.change(appKeyInput, { target: { value: "draft-key" } });
    const appForm = appKeyInput.closest("form");
    await user.click(within(appForm!).getByRole("button", { name: "测试连接" }));

    await waitFor(() => {
      expect(within(appForm!).getByRole("status")).toHaveTextContent("连接正常 · 7 ms");
    });
    expect(testRequestBody(fetchMock, `${SETTINGS_URL}/dingtalk/test`)).toEqual({
      dingtalk_app_key: "draft-key",
      dingtalk_app_secret: "",
      dingtalk_agent_id: "1001",
    });
  });
});

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/settings"]}>
        <ConsoleSettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function okResult(latencyMs: number) {
  return { ok: true, latency_ms: latencyMs, error_code: "", error_message: "" };
}

function settingsFetchMock(
  overrides: Partial<typeof SETTINGS> & Record<string, unknown> = {},
  testResults: Record<string, unknown> = {},
) {
  const payload = { ...SETTINGS, ...overrides };
  return vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === SETTINGS_URL && (!init?.method || init.method === "GET")) {
      return jsonResponse(payload);
    }
    if (url === SETTINGS_URL && init?.method === "PATCH") {
      return jsonResponse(payload);
    }
    if (url === TWO_FACTOR_URL && (!init?.method || init.method === "GET")) {
      return jsonResponse({ supported: true, totp: { enabled: false }, passkeys: [] });
    }
    if (init?.method === "POST" && url in testResults) {
      return jsonResponse(testResults[url]);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

function testRequestBody(fetchMock: ReturnType<typeof settingsFetchMock>, url: string) {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input) === url && init?.method === "POST",
  );
  return JSON.parse(String(call?.[1]?.body));
}

function requestBody(fetchMock: ReturnType<typeof settingsFetchMock>) {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input) === SETTINGS_URL && init?.method === "PATCH",
  );
  return JSON.parse(String(call?.[1]?.body));
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
