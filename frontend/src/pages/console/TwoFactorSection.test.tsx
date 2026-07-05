import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { TwoFactorSection } from "./TwoFactorSection";

const BASE_URL = "/console/api/v1/security/two-factor";

describe("TwoFactorSection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("FF-3: /totp/begin 失败时展示错误而非静默无反馈", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === BASE_URL && (!init?.method || init.method === "GET")) {
        return jsonResponse({ supported: true, totp: { enabled: false }, passkeys: [] });
      }
      if (url === `${BASE_URL}/totp/begin` && init?.method === "POST") {
        return jsonResponse({ error: { code: "CONFLICT", message: "当前会话已失效, 请重新登录" } }, 409);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<TwoFactorSection />);

    const enableButton = await screen.findByRole("button", { name: "启用" });
    await user.click(enableButton);

    await waitFor(() => expect(screen.getByText("当前会话已失效, 请重新登录")).toBeVisible());
    expect(enableButton).not.toBeDisabled();
  });

  test("BS-14: 停用 TOTP 请求体携带 current_password", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === BASE_URL && (!init?.method || init.method === "GET")) {
        return jsonResponse({ supported: true, totp: { enabled: true }, passkeys: [] });
      }
      if (url === `${BASE_URL}/totp/disable` && init?.method === "POST") {
        return jsonResponse({ supported: true, totp: { enabled: false }, passkeys: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<TwoFactorSection />);

    await user.click(await screen.findByRole("button", { name: "停用" }));
    await user.type(screen.getByLabelText("当前 6 位验证码"), "123456");
    await user.type(screen.getByLabelText("当前登录密码"), "s3cret-pw");
    await user.click(screen.getByRole("button", { name: "确认停用" }));

    await waitFor(() => {
      const disableCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === `${BASE_URL}/totp/disable` && init?.method === "POST",
      );
      expect(disableCall).toBeDefined();
      expect(JSON.parse(String(disableCall?.[1]?.body))).toEqual({ code: "123456", current_password: "s3cret-pw" });
    });
  });

  test("BS-14: 删除通行密钥的 DELETE 请求体携带 current_password", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === BASE_URL && (!init?.method || init.method === "GET")) {
        return jsonResponse({
          supported: true,
          totp: { enabled: false },
          passkeys: [{ id: 5, name: "MacBook", created_at: null, last_used_at: null }],
        });
      }
      if (url === `${BASE_URL}/passkeys/5` && init?.method === "DELETE") {
        return jsonResponse({ supported: true, totp: { enabled: false }, passkeys: [] });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<TwoFactorSection />);

    await user.click(await screen.findByRole("button", { name: "删除" }));
    await user.type(screen.getByLabelText("当前登录密码"), "s3cret-pw");
    await user.click(screen.getByRole("button", { name: "确认删除" }));

    await waitFor(() => {
      const deleteCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === `${BASE_URL}/passkeys/5` && init?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
      expect(JSON.parse(String(deleteCall?.[1]?.body))).toEqual({ current_password: "s3cret-pw" });
    });
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

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
