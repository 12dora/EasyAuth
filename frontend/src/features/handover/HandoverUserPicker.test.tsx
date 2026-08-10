import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { HandoverUserPicker } from "./HandoverUserPicker";

function renderPicker(onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HandoverUserPicker surface="portal" taskId={1} value={null} onChange={onChange} aria-label="接收人" />
    </QueryClientProvider>,
  );
}

describe("HandoverUserPicker", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  test("输入防抖 300ms 后请求 candidates", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = vi.fn<typeof fetch>(async () =>
      new Response(JSON.stringify({ items: [{ user_id: "u-1", name: "张某某", department: "销售" }] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPicker();

    const input = screen.getByRole("combobox", { name: "接收人" });
    await user.click(input);
    // 打开时可能先拉空 q；再输入后须再 debounce 300ms
    await user.type(input, "张");
    const callsBefore = fetchMock.mock.calls.filter(([url]) => String(url).includes("q=%E5%BC%A0")).length;
    expect(callsBefore).toBe(0);
    await vi.advanceTimersByTimeAsync(300);
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url).includes("purpose=receiver") && String(url).includes("q=%E5%BC%A0")),
      ).toBe(true);
    });
  });

  test("空集渲染", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    const user = userEvent.setup();
    renderPicker();
    await user.click(screen.getByRole("combobox", { name: "接收人" }));
    expect(await screen.findByTestId("handover-user-picker-empty")).toBeVisible();
  });
});
