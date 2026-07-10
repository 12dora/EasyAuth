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

    const dingtalkForm = (await screen.findByLabelText(/AppKey/)).closest("form");
    expect(dingtalkForm).not.toBeNull();
    const appKeyInput = within(dingtalkForm!).getByLabelText(/AppKey/);
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

function settingsFetchMock() {
  return vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === SETTINGS_URL && (!init?.method || init.method === "GET")) {
      return jsonResponse(SETTINGS);
    }
    if (url === SETTINGS_URL && init?.method === "PATCH") {
      return jsonResponse(SETTINGS);
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
