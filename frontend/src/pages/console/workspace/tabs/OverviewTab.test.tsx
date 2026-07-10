import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { OverviewTab } from "./OverviewTab";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("概览显示权威授权组数量", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/configuration-status")) {
        return jsonResponse({ status: "ready", data: [] });
      }
      if (url.endsWith("/memberships")) {
        return jsonResponse({ data: [] });
      }
      return jsonResponse({}, 404);
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <OverviewTab
        appKey="demo"
        app={{
          id: 1,
          app_key: "demo",
          name: "Demo",
          authorization_group_count: 7,
        }}
      />
    </QueryClientProvider>,
  );

  const metric = screen.getByText("授权组").parentElement;
  expect(metric).not.toBeNull();
  expect(within(metric as HTMLElement).getByText("7")).toBeInTheDocument();
});

test("使用真实成员序列化形状按 membership ID 停用成员", async () => {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/configuration-status")) {
      return jsonResponse({ status: "ready", data: [] });
    }
    if (url.endsWith("/memberships") && !init?.method) {
      return jsonResponse({
        data: [{ id: 42, user_id: "member-42", role: "developer", is_active: true }],
      });
    }
    if (url.endsWith("/memberships/42") && init?.method === "PATCH") {
      return jsonResponse({
        membership: { id: 42, user_id: "member-42", role: "developer", is_active: false },
      });
    }
    return jsonResponse({}, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={client}>
      <OverviewTab appKey="demo" app={{ id: 1, app_key: "demo", name: "Demo", can_manage: true }} />
    </QueryClientProvider>,
  );

  await screen.findByText("member-42");
  const membersPanel = screen.getByRole("heading", { name: "成员" }).closest("section");
  expect(membersPanel).not.toBeNull();
  fireEvent.click(within(membersPanel as HTMLElement).getByRole("button", { name: "停用" }));

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/console/api/v1/apps/demo/memberships/42",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ is_active: false }) }),
    );
  });
});

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
