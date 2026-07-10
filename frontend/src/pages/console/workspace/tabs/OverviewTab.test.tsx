import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
