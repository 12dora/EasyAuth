import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

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
            version: 1,
            is_active: true,
          },
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

    renderWithClient(<IntegrationTab appKey="demo" canManage />);

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
    expect(screen.getByLabelText("钉钉 App Secret")).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "保存新版本" }));
    await waitFor(() => expect(findCall(fetchMock, CHANNEL_URL, "PUT")).toBeDefined());
    expect(JSON.parse(String(findCall(fetchMock, CHANNEL_URL, "PUT")?.[1]?.body))).toEqual({
      name: "EasyTrade 通知",
      dingtalk_app_key: "ding-app-key",
      dingtalk_app_secret: "",
      agent_id: "9001",
    });
    await user.click(screen.getByRole("button", { name: "测试连通性" }));
    await waitFor(() => expect(findCall(fetchMock, `${CHANNEL_URL}/test`, "POST")).toBeDefined());
  });

  test("普通 App owner 不能开平台能力，developer 对通知通道也只读", async () => {
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
        return jsonResponse({ notification_channel: null });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<IntegrationTab appKey="demo" canManage={false} />);

    expect(await screen.findByText("需系统管理员开通")).toBeVisible();
    expect(screen.getByRole("switch", { name: "切换 directory 平台能力" })).toBeDisabled();
    expect(screen.getByLabelText("通道名称")).toBeDisabled();
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
  render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
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
