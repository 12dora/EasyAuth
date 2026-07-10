import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { WebhookTab } from "./WebhookTab";

const CONFIG_URL = "/console/api/v1/apps/demo/webhook-config";

describe("WebhookTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("权威配置 GET 失败后禁止保存和轮换", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ message: "读取失败" }, 500));
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithClient(<WebhookTab appKey="demo" />);

    expect(await screen.findAllByText("Webhook 配置加载失败")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成/轮换密钥" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeEnabled();

    fireEvent.submit(container.querySelector("form")!);
    fireEvent.click(screen.getByRole("button", { name: "生成/轮换密钥" }));

    expect(fetchMock.mock.calls).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  test("权威配置响应缺少契约字段时保持关闭写入", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<WebhookTab appKey="demo" />);

    expect(await screen.findAllByText("Webhook 配置加载失败")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "生成/轮换密钥" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("成功读取未配置状态后允许首次保存", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === CONFIG_URL && !init?.method) {
        return jsonResponse({ webhook_config: null });
      }
      if (String(input) === CONFIG_URL && init?.method === "PUT") {
        return jsonResponse({
          webhook_config: {
            enabled: true,
            secret_configured: true,
            approval_callback_url: "",
            handover_url: "",
            onboard_url: "",
            updated_by: "owner",
            updated_at: "2026-07-10T00:00:00Z",
          },
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<WebhookTab appKey="demo" />);

    expect(await screen.findByText(/尚未配置 Webhook/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(true);
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
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
