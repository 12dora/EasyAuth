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

  test("载荷到达后概览条按现有字段给出三个状态", async () => {
    const fetchMock = settingsFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    renderSettings();

    const summary = (await screen.findByText("钉钉统一认证")).closest("div")?.parentElement;
    expect(summary).not.toBeNull();
    expect(within(summary!).getByText("Authentik")).toBeVisible();
    expect(within(summary!).getByText("服务号")).toBeVisible();
    // 服务号三元组为空: 概览与卡片都应说明回退到统一认证应用, 而不是报未配置。
    expect(within(summary!).getByText("沿用统一认证应用")).toBeVisible();
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

function settingsFetchMock(overrides: Partial<typeof SETTINGS> & Record<string, unknown> = {}) {
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
    throw new Error(`Unexpected fetch: ${url}`);
  });
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
