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

  test("加载期间与错误态不会伪装成未配置", async () => {
    let rejectRequest: ((reason?: unknown) => void) | undefined;
    const fetchMock = vi.fn<typeof fetch>(
      () =>
        new Promise<Response>((_resolve, reject) => {
          rejectRequest = reject;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderWithClient(<WebhookTab appKey="demo" />);

    expect(screen.getByText("加载中")).toBeInTheDocument();
    expect(screen.queryByText("未配置")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();

    rejectRequest?.(new Error("读取失败"));

    expect(await screen.findAllByText("Webhook 配置加载失败")).not.toHaveLength(0);
    expect(screen.queryByText("未配置")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存" })).toBeDisabled();
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
        return jsonResponse(configuredPayload(""));
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

  test("错误态重试成功后按已配置状态要求轮换确认", async () => {
    let getCount = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === CONFIG_URL && !init?.method) {
        getCount += 1;
        if (getCount === 1) {
          return jsonResponse({ message: "读取失败" }, 500);
        }
        return jsonResponse(configuredPayload());
      }
      if (String(input) === CONFIG_URL && init?.method === "PUT") {
        return jsonResponse(configuredPayload());
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<WebhookTab appKey="demo" />);

    expect(await screen.findByRole("button", { name: "重新加载" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "重新加载" }));

    expect(await screen.findByDisplayValue("https://hooks.example.com/approval")).toBeEnabled();
    expect(screen.getByText("已配置")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "生成/轮换密钥" }));

    expect(await screen.findByText("轮换签名密钥")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);

    await user.click(screen.getByRole("button", { name: "确认轮换" }));

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
      expect(putCall).toBeDefined();
      expect(JSON.parse(String(putCall?.[1]?.body))).toMatchObject({ rotate_secret: true });
    });
  });

  test("保存响应畸形时保留已配置状态且轮换仍需确认", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === CONFIG_URL && !init?.method) {
        return jsonResponse(configuredPayload());
      }
      if (String(input) === CONFIG_URL && init?.method === "PUT") {
        return jsonResponse({ webhook_config: null });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<WebhookTab appKey="demo" />);

    expect(await screen.findByDisplayValue("https://hooks.example.com/approval")).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    expect(screen.getByText("已配置")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "生成/轮换密钥" }));

    expect(await screen.findByText("轮换签名密钥")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
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

function configuredPayload(approvalCallbackUrl = "https://hooks.example.com/approval") {
  return {
    webhook_config: {
      enabled: true,
      secret_configured: true,
      approval_callback_url: approvalCallbackUrl,
      handover_url: "",
      onboard_url: "",
      updated_by: "owner",
      updated_at: "2026-07-10T00:00:00Z",
    },
  };
}
