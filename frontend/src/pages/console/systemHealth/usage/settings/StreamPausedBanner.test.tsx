import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { StreamPausedBanner } from "./StreamPausedBanner";

const RESUME_URL = "/console/api/v1/operations/system-health/usage/stream/resume";

const mocks = vi.hoisted(() => ({
  stream: { paused: false, paused_at: null as string | null, can_resume: false },
}));

// 恢复接口地址来自同一个模块, 必须保留真实导出。
vi.mock("../useUsageData", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../useUsageData")>()),
  useUsageSummary: () => ({ data: { stream: mocks.stream }, isLoading: false, error: null }),
}));

describe("StreamPausedBanner", () => {
  beforeEach(() => {
    mocks.stream = { paused: false, paused_at: null, can_resume: false };
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("未暂停时什么都不渲染", () => {
    const { container } = renderBanner();

    expect(container).toBeEmptyDOMElement();
  });

  test("暂停时展示暂停时间与恢复入口", () => {
    mocks.stream = { paused: true, paused_at: "2026-09-21T02:00:00Z", can_resume: true };
    renderBanner();

    expect(screen.getByRole("alert")).toHaveTextContent("Stream 已暂停");
    expect(screen.getByRole("button", { name: "立即恢复" })).toBeEnabled();
  });

  test("确认后调用恢复接口", async () => {
    mocks.stream = { paused: true, paused_at: "2026-09-21T02:00:00Z", can_resume: true };
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ stream: { paused: false, paused_at: null, can_resume: false } }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderBanner();

    await userEvent.click(screen.getByRole("button", { name: "立即恢复" }));
    expect(await screen.findByText("立即恢复 Stream 连接？")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "恢复连接" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(RESUME_URL, expect.objectContaining({ method: "POST" })),
    );
  });

  test("不可手动恢复时按钮禁用并说明原因", () => {
    mocks.stream = { paused: true, paused_at: null, can_resume: false };
    renderBanner();

    expect(screen.getByRole("button", { name: "立即恢复" })).toBeDisabled();
    expect(screen.getByText("当前不可手动恢复，请等待下个配额周期开始。")).toBeVisible();
  });

  test("恢复失败时就地展示错误", async () => {
    mocks.stream = { paused: true, paused_at: null, can_resume: true };
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ error: { code: "CONFLICT", message: "stream is not paused" } }, 409),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderBanner();

    await userEvent.click(screen.getByRole("button", { name: "立即恢复" }));
    await userEvent.click(await screen.findByRole("button", { name: "恢复连接" }));

    expect(await screen.findByText("恢复 Stream 失败")).toBeVisible();
    expect(screen.getByText("stream is not paused")).toBeVisible();
  });
});

function renderBanner() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <StreamPausedBanner />
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
