import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { HandoverAction, HandoverActionStatus, HandoverTaskDetail } from "../../lib/domain";
import { PortalHandoverDetail } from "./PortalHandoverDetail";

const ALL_STATUSES = [
  "pending",
  "previewed",
  "executing",
  "async_pending",
  "done",
  "failed",
  "skipped",
  "blocked",
  "async_attention_required",
] as const satisfies readonly HandoverActionStatus[];

function baseAction(status: HandoverActionStatus, patch: Partial<HandoverAction> = {}): HandoverAction {
  return {
    app_key: status,
    app_name: `App-${status}`,
    status,
    blocked_reason: status === "blocked" ? "capability_undeclared" : "",
    skip_reason: status === "skipped" ? "人工跳过" : "",
    skipped_by: status === "skipped" ? "admin-1" : "",
    skipped_at: status === "skipped" ? "2026-08-01T00:00:00Z" : null,
    skip_history:
      status === "skipped"
        ? [{ generation: 1, actor_id: "admin-1", reason: "人工跳过", skipped_at: "2026-08-01T00:00:00Z" }]
        : [],
    last_error: status === "failed" ? "下游超时" : "",
    allowed_actions:
      status === "pending"
        ? ["preview"]
        : status === "previewed"
          ? ["preview", "execute"]
          : status === "failed"
            ? ["retry"]
            : [],
    confirm_version: 1,
    overrides_version: 1,
    batch_progress: null,
    asset_types:
      status === "previewed"
        ? [
            {
              type: "customer",
              label: "名下客户",
              count: 187,
              detail_supported: true,
              releasable: true,
              default_action: "transfer",
              default_to_user: { user_id: "u-9", name: "张某某" },
              override_count: 2,
            },
            {
              type: "order",
              label: "在途订单",
              count: 23,
              detail_supported: true,
              releasable: true,
              default_action: "transfer",
              default_to_user: { user_id: "u-9", name: "张某某" },
              override_count: 0,
            },
          ]
        : [],
    approval_instance_warning: null,
    grant_receiver: null,
    summary:
      status === "done"
        ? { customer: { transferred: 10, released: 0, skipped: 0, merged: 0, failed: 0 } }
        : null,
    data_completed_at: status === "failed" && patch.data_completed_at !== undefined ? patch.data_completed_at : null,
    ...patch,
  };
}

function taskWithActions(actions: HandoverAction[]): HandoverTaskDetail {
  return {
    id: 10,
    kind: "offboard",
    status: "in_progress",
    generation: 1,
    subject: { user_id: "s1", name: "王某某", department: "华东" },
    assignee: { user_id: "a1", name: "李某某" },
    assignee_state: "manager",
    escalation_level: 1,
    escalation: {
      deadline: "2026-08-24T00:00:00Z",
      days_left: 9,
      level: 1,
      deferred_at: null,
      defer_history: [],
    },
    reason: "离职",
    created_at: "2026-08-10T00:00:00Z",
    actions,
    team_items: [],
  };
}

function renderDetail(task: HandoverTaskDetail) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.includes("/handover-tasks/10") && !url.includes("/actions/")) {
        return new Response(JSON.stringify({ handover_task: task }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/handover-candidates")) {
        return new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url.includes("/assets/")) {
        return new Response(JSON.stringify({ items: [], page: 1, page_size: 50, total: 0, unfiltered_total: null, stale: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected ${url}`);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/portal/handovers/10"]}>
        <Routes>
          <Route path="/portal/handovers/:taskId" element={<PortalHandoverDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PortalHandoverDetail", () => {
  afterEach(() => vi.unstubAllGlobals());

  // 类型驱动：HandoverActionStatus 联合类型每个值各一条形态断言
  test.each(ALL_STATUSES)("action status %s 有对应形态", async (status) => {
    const actions = [baseAction(status)];
    if (status === "failed") {
      actions.push(baseAction("failed", { app_key: "failed-data", app_name: "FailedData", data_completed_at: "2026-08-01T00:00:00Z", allowed_actions: [] }));
    }
    renderDetail(taskWithActions(actions));
    expect(await screen.findByTestId(`action-panel-${status === "failed" ? "failed" : status}`)).toBeVisible();

    if (status === "blocked") {
      expect(screen.getByText(/尚未实现数据交接/)).toBeVisible();
      expect(screen.queryByRole("button", { name: /跳过|预演|执行/ })).toBeNull();
    }
    if (status === "skipped") {
      expect(screen.getByText(/admin-1/)).toBeVisible();
    }
    if (status === "async_attention_required") {
      expect(screen.getByText(/异步交接长时间没有给出结果/)).toBeVisible();
    }
    if (status === "pending") {
      expect(screen.getByRole("button", { name: "预演" })).toBeVisible();
    }
    if (status === "previewed") {
      expect(screen.getByRole("button", { name: "执行交接" })).toBeVisible();
    }
    if (status === "executing" || status === "async_pending") {
      expect(screen.getByText(/交接执行中/)).toBeVisible();
    }
    if (status === "done") {
      expect(screen.getByText(/已转交/)).toBeVisible();
    }
    if (status === "failed") {
      expect(screen.getByText("数据未移交，权限未变更")).toBeVisible();
      expect(screen.getByText("数据已移交成功，权限转移失败")).toBeVisible();
    }
  });

  test("执行前二次确认文案含数量与接收人", async () => {
    const user = userEvent.setup();
    renderDetail(taskWithActions([baseAction("previewed")]));
    await user.click(await screen.findByRole("button", { name: "执行交接" }));
    const body = await screen.findByTestId("execute-confirm-body");
    expect(body).toHaveTextContent("187");
    expect(body).toHaveTextContent("名下客户");
    expect(body).toHaveTextContent("张某某");
    expect(body).toHaveTextContent("2");
  });
});
