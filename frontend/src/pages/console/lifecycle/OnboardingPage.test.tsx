import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { OnboardingPage } from "./OnboardingPage";
import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "../../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/翻页都要重建整棵表格, 默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const TEMPLATES = Array.from({ length: 12 }, (_, index) => ({
  id: index + 1,
  name: `模板${index + 1}`,
  description: index % 2 === 0 ? "常用" : "备用",
  is_active: index % 2 === 0,
  items: [],
  created_at: "2026-07-01T09:00:00Z",
  updated_at: "2026-07-01T09:00:00Z",
}));

describe("OnboardingPage 模板表格", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("接口一次返回全量时表格自己分页", async () => {
    stubTemplates();
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByText("模板1")).toBeVisible();
    expect(bodyRowCount()).toBe(10);
    expect(screen.getByText("第 1-10 条 / 共 12 条")).toBeVisible();

    await user.click(screen.getByTitle("2"));

    expect(await screen.findByText("模板11")).toBeVisible();
    expect(bodyRowCount()).toBe(2);
  });

  test("状态筛选在表头, 客户端按启用/停用过滤", async () => {
    stubTemplates();
    const user = userEvent.setup();

    renderPage();

    await screen.findByText("模板1");
    const dropdown = await openHeaderFilter(user, "状态");
    await user.click(within(dropdown).getByText("停用"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(bodyRowCount()).toBe(6));
    expect(screen.getByText("模板2")).toBeVisible();
    expect(screen.queryByText("模板1")).not.toBeInTheDocument();
  });
});

function stubTemplates() {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/console/api/v1/lifecycle/onboarding-templates") {
        return jsonResponse({ data: TEMPLATES });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }),
  );
}

function bodyRowCount(): number {
  return document.querySelectorAll(".ant-table-tbody tr.ant-table-row").length;
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OnboardingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

