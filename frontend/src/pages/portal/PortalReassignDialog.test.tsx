import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PortalReassignDialog } from "./PortalReassignDialog";

describe("PortalReassignDialog", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("理由 <10 字符不可提交；403 文案", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("purpose=reassign_subject")) {
        return new Response(
          JSON.stringify({ items: [{ user_id: "u-sub", name: "下属甲", department: "销售" }] }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.includes("handover-app-options")) {
        return new Response(JSON.stringify({ items: [{ app_key: "easytrade", app_name: "EasyTrade" }] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/handover-tasks/reassign") && method === "POST") {
        return new Response(
          JSON.stringify({
            error: { code: "PERMISSION_DENIED", message: "forbidden", details: { reason: "out_of_managed_scope" } },
          }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        );
      }
      throw new Error(`${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <PortalReassignDialog onClose={() => undefined} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    // 选转出方
    const subjectInput = screen.getByRole("textbox", { name: "转出方" });
    await user.click(subjectInput);
    await user.click(await screen.findByRole("button", { name: /下属甲/ }));
    // 选应用
    await user.click(await screen.findByRole("checkbox", { name: /EasyTrade/ }));
    // 理由过短
    const reasonInput = screen.getByRole("textbox", { name: "理由" });
    await user.type(reasonInput, "太短了");
    await user.click(screen.getByRole("button", { name: "创建移交单" }));
    expect(screen.getByText("理由至少 10 个字符")).toBeVisible();
    expect(fetchMock.mock.calls.some(([u, i]) => String(u).includes("/reassign") && i?.method === "POST")).toBe(false);

    await user.clear(reasonInput);
    await user.type(reasonInput, "这是足够长的移交理由说明");
    await user.click(screen.getByRole("button", { name: "创建移交单" }));
    await waitFor(() => {
      expect(screen.getByText("你没有该员工的管理权限，请联系管理员处理。")).toBeVisible();
    });
  });
});

