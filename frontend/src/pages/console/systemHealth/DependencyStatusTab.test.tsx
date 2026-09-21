import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "../../../components/antd/testing";
import { ToastProvider } from "../../../components/ui/Toast";
import { DependencyStatusTab } from "./DependencyStatusTab";

// antd Table 在 jsdom 里每次筛选/翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const DEPENDENCIES_URL = "/console/api/v1/operations/system-health/dependencies";
const CHECKS_URL = `${DEPENDENCIES_URL}/checks`;

describe("DependencyStatusTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("依赖状态在客户端筛选, 不再请求后端", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === DEPENDENCIES_URL) {
        return jsonResponse({
          data: [
            healthRow({ component: "authentik", status: "healthy", summary: "正常" }),
            healthRow({ component: "dingtalk", status: "unhealthy", summary: "调用失败", error_summary: "HTTP 500" }),
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderTab();

    expect(await screen.findByText("authentik")).toBeVisible();

    const statusFilter = await openHeaderFilter(user, "状态");
    await user.click(within(statusFilter).getByText("异常"));
    await user.click(within(statusFilter).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(screen.queryByText("authentik")).not.toBeInTheDocument());
    expect(screen.getByText("dingtalk")).toBeVisible();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("立即检测成功后按响应刷新表格, 不清空行", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === DEPENDENCIES_URL) {
        return jsonResponse({ data: [healthRow({ status: "healthy", summary: "正常" })] });
      }
      if (url === CHECKS_URL && init?.method === "POST") {
        return jsonResponse({
          data: [
            healthRow({
              status: "unhealthy",
              summary: "调用失败",
              error_summary: "HTTP 500",
              last_checked_at: "2026-07-02T01:00:00Z",
            }),
          ],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderTab();

    expect(await screen.findByText("正常")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "立即检测" }));

    // 检测响应直接写回查询缓存: 行必须仍在, 且换成最新结果。
    expect(await screen.findByText("调用失败")).toBeVisible();
    expect(screen.getByText("authentik")).toBeVisible();
    expect(screen.queryByText("暂无依赖检测结果")).not.toBeInTheDocument();
  });

  test("立即检测失败时以 toast 报错, 表格保留原有行", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === DEPENDENCIES_URL) {
        return jsonResponse({ data: [healthRow({ status: "healthy", summary: "正常" })] });
      }
      if (url === CHECKS_URL && init?.method === "POST") {
        return jsonResponse({ detail: "探测超时" }, 502);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ delay: null });

    renderTab();

    expect(await screen.findByText("正常")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "立即检测" }));

    expect(await screen.findByText("依赖检测执行失败")).toBeVisible();
    expect(screen.getByText("authentik")).toBeVisible();
  });

  test("一行都没有时加载失败换成整块失败态并可重试", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === DEPENDENCIES_URL) {
        return jsonResponse({ detail: "上游不可用" }, 503);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderTab();

    expect(await screen.findByText("依赖状态加载失败")).toBeVisible();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeVisible();
  });

  test("行缺少契约字段时不静默兜底, 直接走失败态", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === DEPENDENCIES_URL) {
        // summary 缺失: 后端契约违约, 必须在取数阶段就炸出来。
        return jsonResponse({ data: [{ component: "authentik", status: "healthy", error_summary: "", last_checked_at: null }] });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderTab();

    expect(await screen.findByText("依赖状态加载失败")).toBeVisible();
    expect(screen.getByText(/dependency\.summary/)).toBeVisible();
  });
});

function healthRow(overrides: Record<string, unknown> = {}) {
  return {
    component: "authentik",
    status: "healthy",
    summary: "正常",
    error_summary: "",
    last_checked_at: "2026-07-02T00:00:00Z",
    ...overrides,
  };
}

function renderTab() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return renderWithAntd(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <DependencyStatusTab />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
