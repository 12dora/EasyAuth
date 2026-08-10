import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { AppShellOutletContext } from "../../../components/AppShell";
import { HandoverTaskDetail } from "./HandoverTaskDetail";

function detailPayload(assigneeState: "manager" | "superuser_pool" = "manager", deferredAt: string | null = null) {
  return {
    handover_task: {
      id: 1,
      kind: "offboard",
      status: "in_progress",
      generation: 1,
      subject: { user_id: "u-1", name: "张三", email: "z@example.com", department: "销售", status: "departed" },
      assignee: assigneeState === "superuser_pool" ? null : { user_id: "a1", name: "主管" },
      assignee_state: assigneeState,
      escalation_level: 0,
      escalation: {
        deadline: assigneeState === "superuser_pool" ? null : "2026-08-24T00:00:00Z",
        days_left: assigneeState === "superuser_pool" ? null : 9,
        level: 0,
        deferred_at: deferredAt,
        defer_history: deferredAt
          ? [{ escalation_level: 0, actor_id: "su-1", at: deferredAt, reason: "业务高峰顺延一次" }]
          : [],
      },
      reason: "离职",
      created_at: "2026-07-01T09:00:00Z",
      created_by: "admin",
      actions: [
        {
          app_key: "easytrade",
          app_name: "EasyTrade",
          status: "blocked",
          blocked_reason: "capability_undeclared",
          skip_reason: "",
          skipped_by: "",
          skipped_at: null,
          skip_history: [],
          last_error: "",
          allowed_actions: ["skip"],
          confirm_version: 0,
          overrides_version: 0,
          batch_progress: null,
          asset_types: [],
          approval_instance_warning: null,
          grant_receiver: null,
          summary: null,
          data_completed_at: null,
        },
      ],
      team_items: [],
      transfer_plan: null,
    },
  };
}

function renderDetail(context: AppShellOutletContext, payload = detailPayload()) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/console/api/v1/lifecycle/handover-tasks/1" && method === "GET") {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/skip") && method === "POST") {
        return new Response(
          JSON.stringify({
            action: { ...payload.handover_task.actions[0], status: "skipped", skip_reason: "管理员确认无数据", skipped_by: "su" },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/claim") || url.endsWith("/escalation/defer")) {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`${method} ${url}`);
    }),
  );

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/lifecycle/handover-tasks/1"]}>
        <Routes>
          <Route path="/console/lifecycle/handover-tasks/:taskId" element={<HandoverTaskDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// Outlet context is read via useOutletContext; provide by wrapping with a parent route context.
// AppShellOutletContext is normally from AppShell; for unit tests we inject via react-router Outlet context.
import { Outlet } from "react-router-dom";

function renderWithOutlet(context: AppShellOutletContext, payload = detailPayload()) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url === "/console/api/v1/lifecycle/handover-tasks/1" && method === "GET") {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.endsWith("/skip") && method === "POST") {
        return new Response(
          JSON.stringify({
            action: {
              ...payload.handover_task.actions[0],
              status: "skipped",
              skip_reason: "管理员确认无数据需要跳过",
              skipped_by: "su",
              skipped_at: "2026-08-10T00:00:00Z",
              skip_history: [
                {
                  generation: 1,
                  actor_id: "su",
                  reason: "管理员确认无数据需要跳过",
                  skipped_at: "2026-08-10T00:00:00Z",
                },
              ],
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      if (url.endsWith("/claim") || url.endsWith("/escalation/defer")) {
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`${method} ${url}`);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Shell() {
    return <Outlet context={context} />;
  }
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/lifecycle/handover-tasks/1"]}>
        <Routes>
          <Route element={<Shell />}>
            <Route path="/console/lifecycle/handover-tasks/:taskId" element={<HandoverTaskDetail />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HandoverTaskDetail", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("跳过对话框必填理由", async () => {
    const user = userEvent.setup();
    renderWithOutlet({ currentUserId: "su-1", isSuperuser: true });
    await user.click(await screen.findByRole("button", { name: "强行跳过" }));
    const confirm = screen.getByRole("button", { name: "确认跳过" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("跳过理由"), "管理员确认无数据需要跳过");
    expect(confirm).toBeEnabled();
  });

  test("认领与顺延按钮的显示条件", async () => {
    // superuser_pool → 显示认领
    renderWithOutlet({ currentUserId: "su-1", isSuperuser: true }, detailPayload("superuser_pool"));
    expect(await screen.findByTestId("claim-button")).toBeVisible();
    expect(screen.getByTestId("defer-button")).toBeDisabled();
  });

  test("已顺延时顺延按钮禁用", async () => {
    renderWithOutlet(
      { currentUserId: "su-1", isSuperuser: true },
      detailPayload("manager", "2026-08-01T00:00:00Z"),
    );
    expect(await screen.findByTestId("defer-button")).toBeDisabled();
    expect(screen.getByText(/业务高峰顺延一次/)).toBeVisible();
  });

  test("本地管理员认领按钮禁用", async () => {
    renderWithOutlet(
      { currentUserId: "local-admin:break-glass", isSuperuser: true },
      detailPayload("superuser_pool"),
    );
    expect(await screen.findByTestId("claim-button")).toBeDisabled();
  });
});
