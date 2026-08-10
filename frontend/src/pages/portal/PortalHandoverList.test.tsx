import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PortalHandoverList } from "./PortalHandoverList";

function listPayload() {
  return {
    handover_tasks: {
      as_assignee: [
        {
          id: 1,
          kind: "offboard",
          status: "in_progress",
          generation: 1,
          subject: { user_id: "s1", name: "王某某", department: "华东销售部" },
          assignee: { user_id: "a1", name: "我" },
          assignee_state: "manager",
          escalation_level: 0,
          escalation: { deadline: "2026-08-24T00:00:00Z", days_left: 9, level: 0, deferred_at: null, defer_history: [] },
          reason: "离职",
          created_at: "2026-08-10T00:00:00Z",
          pending_app_count: 2,
          blocked_app_count: 1,
          total_asset_count: 251,
        },
        {
          id: 2,
          kind: "reassign",
          status: "in_progress",
          generation: 1,
          subject: { user_id: "s2", name: "李某某", department: "研发" },
          assignee: { user_id: "a1", name: "我" },
          assignee_state: "manager",
          escalation_level: 0,
          escalation: { deadline: "2026-08-12T00:00:00Z", days_left: 2, level: 0, deferred_at: null, defer_history: [] },
          reason: "移交",
          created_at: "2026-08-10T00:00:00Z",
          pending_app_count: 1,
          blocked_app_count: 0,
          total_asset_count: 10,
        },
      ],
      as_subject: [
        {
          id: 3,
          kind: "pre_offboard",
          status: "in_progress",
          generation: 1,
          subject: { user_id: "me", name: "我" },
          assignee: { user_id: "me", name: "我" },
          assignee_state: "subject",
          escalation_level: 0,
          escalation: { deadline: "2026-08-20T00:00:00Z", days_left: 5, level: 0, deferred_at: null, defer_history: [] },
          reason: "提前",
          created_at: "2026-08-10T00:00:00Z",
          pending_app_count: 1,
          blocked_app_count: 0,
          total_asset_count: 3,
        },
      ],
    },
  };
}

describe("PortalHandoverList", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("两分区渲染；剩余天数配色分档；blocked 提示无跳过按钮", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url.includes("/me/handover-tasks")) {
          return new Response(JSON.stringify(listPayload()), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("purpose=reassign_subject")) {
          return new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(url);
      }),
    );

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <PortalHandoverList />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByText("待我处理")).toBeVisible();
    expect(screen.getByText("我发起的")).toBeVisible();
    expect(await screen.findByText((content) => content.includes("王某某"))).toBeVisible();
    expect(screen.getByText((content) => content.includes("李某某"))).toBeVisible();
    expect(screen.getByTestId("blocked-hint-1")).toHaveTextContent("1 个应用未接入交接");
    expect(screen.queryByRole("button", { name: /跳过/ })).toBeNull();

    // days_left=9 → neutral；days_left=2 → signal（02 §5.1）
    const days9 = screen.getByTestId("days-left-1");
    const days2 = screen.getByTestId("days-left-2");
    const days9Class = days9.querySelector("span")?.className ?? days9.className;
    const days2Class = days2.querySelector("span")?.className ?? days2.className;
    expect(days9Class).toMatch(/border-ink\/20/);
    expect(days9Class).not.toMatch(/signal/);
    expect(days2Class).toMatch(/signal/);
  });
});

