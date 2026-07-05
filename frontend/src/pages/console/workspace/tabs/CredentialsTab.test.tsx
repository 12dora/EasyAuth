import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { CredentialsTab } from "./CredentialsTab";

describe("CredentialsTab(FF-4)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("创建请求在途时重复点击只发出一次 POST", async () => {
    const createUrl = "/console/api/v1/apps/demo/credentials/static-tokens";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/apps/demo/credentials" && !init?.method) {
        return jsonResponse({ data: [] });
      }
      if (url === createUrl && init?.method === "POST") {
        // 让创建请求保持在途, 从而 isCreating 维持为真, 按钮禁用。
        return new Promise<Response>(() => {});
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithClient(<CredentialsTab appKey="demo" />);

    await user.click(await screen.findByRole("button", { name: "新建" }));
    await user.type(screen.getByLabelText("凭据名称"), "生产凭据");

    const staticTokenButton = screen.getByRole("button", { name: /静态 token/ });
    await user.click(staticTokenButton);
    expect(staticTokenButton).toBeDisabled();
    await user.click(staticTokenButton);

    const postCalls = fetchMock.mock.calls.filter(
      ([input, init]) => String(input) === createUrl && init?.method === "POST",
    );
    expect(postCalls).toHaveLength(1);
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
