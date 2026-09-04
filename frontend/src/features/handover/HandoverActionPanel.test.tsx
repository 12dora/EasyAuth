import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { HandoverAction, HandoverTaskDetail } from "../../lib/domain";
import { HandoverActionPanel } from "./HandoverActionPanel";

function baseAction(patch: Partial<HandoverAction> = {}): HandoverAction {
  return {
    app_key: "easytrade",
    app_name: "EasyTrade",
    app_alias: "易交易",
    status: "previewed",
    blocked_reason: "",
    skip_reason: "",
    skipped_by: "",
    skipped_at: null,
    skip_history: [],
    last_error: "",
    allowed_actions: ["preview", "execute"],
    confirm_version: 1,
    overrides_version: 1,
    batch_progress: null,
    asset_types: [
      {
        type: "customer",
        label: "名下客户",
        count: 2,
        detail_supported: true,
        releasable: true,
        default_action: "skip",
        default_to_user: null,
        override_count: 0,
      },
    ],
    approval_instance_warning: null,
    grant_receiver: { user_id: "u-old", name: "旧接收人" },
    summary: null,
    data_completed_at: null,
    ...patch,
  };
}

function baseTask(patch: Partial<HandoverTaskDetail> = {}): HandoverTaskDetail {
  return {
    id: 42,
    kind: "offboard",
    status: "in_progress",
    generation: 1,
    subject: { user_id: "s1", name: "王某某", email: "w@example.com", department: "华东", status: "active" },
    assignee: { user_id: "a1", name: "李某某" },
    assignee_state: "manager",
    escalation_level: 0,
    escalation: {
      deadline: null,
      days_left: null,
      level: 0,
      deferred_at: null,
      defer_history: [],
    },
    reason: "离职",
    created_at: "2026-08-10T00:00:00Z",
    actions: [],
    team_items: [],
    ...patch,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function reasonResponse(status: number, reason: string, message = reason) {
  return new Response(
    JSON.stringify({
      error: {
        code: status === 412 ? "PRECONDITION_FAILED" : "CONFLICT",
        message,
        details: { reason },
      },
    }),
    { status, headers: { "Content-Type": "application/json" } },
  );
}

function renderPanel(options: {
  action?: HandoverAction;
  task?: HandoverTaskDetail;
  onTaskRefresh?: () => void;
  onActionReplace?: (action: HandoverAction) => void;
  queryClient?: QueryClient;
}) {
  const action = options.action ?? baseAction();
  const task = options.task ?? baseTask();
  const client =
    options.queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onTaskRefresh = options.onTaskRefresh ?? vi.fn();
  const onActionReplace = options.onActionReplace ?? vi.fn();
  return {
    client,
    onTaskRefresh,
    onActionReplace,
    ...render(
      <QueryClientProvider client={client}>
        <HandoverActionPanel
          surface="portal"
          task={task}
          action={action}
          onTaskRefresh={onTaskRefresh}
          onActionReplace={onActionReplace}
        />
      </QueryClientProvider>,
    ),
  };
}

function deferredResponse() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("HandoverActionPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("应用标题走统一展示名: 有别名拼成「别名(技术名)」, 没别名只显示技术名", () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse({})));

    const { unmount } = renderPanel({ action: baseAction({ status: "pending", allowed_actions: [] }) });
    expect(screen.getByText("易交易(EasyTrade)")).toBeVisible();
    unmount();

    renderPanel({ action: baseAction({ status: "pending", allowed_actions: [], app_alias: "" }) });
    expect(screen.getByText("EasyTrade")).toBeVisible();
  });

  test("ea-fe-panels-01: grant_receiver PATCH 进行中禁用执行", async () => {
    const grantGate = deferredResponse();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/handover-candidates")) {
        return jsonResponse({
          items: [
            { user_id: "u-new", name: "新接收人", department: "销售" },
            { user_id: "u-old", name: "旧接收人", department: "销售" },
          ],
        });
      }
      if (url.includes("/actions/easytrade") && method === "PATCH") {
        return grantGate.promise;
      }
      if (url.includes("/assets/")) {
        return jsonResponse({ items: [], page: 1, page_size: 50, total: 0, unfiltered_total: null, stale: false });
      }
      throw new Error(`unexpected ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPanel({});

    const executeBtn = screen.getByTestId("execute-handover");
    expect(executeBtn).toBeEnabled();

    // 权限接收人选择器未绑 aria-label，按当前值定位
    const grantPicker = screen.getByDisplayValue("旧接收人");
    await user.click(grantPicker);
    await user.click(await screen.findByRole("option", { name: /新接收人/ }));

    await waitFor(() => {
      expect(executeBtn).toBeDisabled();
    });

    // 释放挂起 PATCH，避免泄漏
    grantGate.resolve(
      jsonResponse({
        action: baseAction({
          grant_receiver: { user_id: "u-new", name: "新接收人" },
          confirm_version: 2,
        }),
      }),
    );
  });

  test("ea-fe-panels-02: execute 412 清掉 items/overrides 缓存并关闭确认", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["handover", "overrides", "portal", "42", "easytrade", "customer", 0], {
      overrides_version: 9,
      overrides: [{ asset_id: "stale", action: "skip", label: "stale" }],
    });
    client.setQueryData(["handover", "items", "portal", "42", "easytrade", "customer", 0, 1, ""], {
      items: [{ id: "stale", label: "stale", hint: "" }],
      page: 1,
      page_size: 50,
      total: 1,
      unfiltered_total: 1,
      stale: false,
    });

    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/execute") && method === "POST") {
        return reasonResponse(412, "snapshot_stale");
      }
      if (url.includes("/handover-candidates")) {
        return jsonResponse({ items: [] });
      }
      throw new Error(`unexpected ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onTaskRefresh = vi.fn();
    const user = userEvent.setup();
    renderPanel({ queryClient: client, onTaskRefresh });

    await user.click(screen.getByTestId("execute-handover"));
    await user.click(await screen.findByTestId("execute-confirm"));

    await waitFor(() => {
      expect(onTaskRefresh).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("execute-confirm")).not.toBeInTheDocument();
    expect(screen.getByText("清单已变化，请重新预演")).toBeVisible();

    const leftover = client.getQueryCache().findAll({
      predicate: (query) => {
        const key = query.queryKey;
        return (
          key[0] === "handover" &&
          (key[1] === "items" || key[1] === "overrides") &&
          key[4] === "easytrade" &&
          query.state.data !== undefined
        );
      },
    });
    expect(leftover).toHaveLength(0);
  });

  test("ea-fe-panels-04: done 摘要 null/空对象显示空态；零值 merged/failed 仍展示", () => {
    const { rerender, client } = (() => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const view = render(
        <QueryClientProvider client={client}>
          <HandoverActionPanel
            surface="portal"
            task={baseTask()}
            action={baseAction({ status: "done", allowed_actions: [], summary: null })}
            onTaskRefresh={vi.fn()}
            onActionReplace={vi.fn()}
          />
        </QueryClientProvider>,
      );
      return { ...view, client };
    })();

    expect(screen.getByTestId("done-summary-empty")).toBeVisible();

    rerender(
      <QueryClientProvider client={client}>
        <HandoverActionPanel
          surface="portal"
          task={baseTask()}
          action={baseAction({ status: "done", allowed_actions: [], summary: {} })}
          onTaskRefresh={vi.fn()}
          onActionReplace={vi.fn()}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByTestId("done-summary-empty")).toBeVisible();

    rerender(
      <QueryClientProvider client={client}>
        <HandoverActionPanel
          surface="portal"
          task={baseTask()}
          action={baseAction({
            status: "done",
            allowed_actions: [],
            summary: {
              customer: { transferred: 3, released: 1, skipped: 0, merged: 0, failed: 0 },
            },
          })}
          onTaskRefresh={vi.fn()}
          onActionReplace={vi.fn()}
        />
      </QueryClientProvider>,
    );
    const row = screen.getByTestId("done-summary-customer");
    expect(within(row).getByText(/已转交 3/)).toBeVisible();
    expect(within(row).getByText(/已合并 0/)).toBeVisible();
    expect(within(row).getByText(/失败 0/)).toBeVisible();
  });

  test("ea-fe-panels-05: confirm_version_stale 关闭确认并阻塞到新版本", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/execute") && method === "POST") {
        return reasonResponse(409, "confirm_version_stale");
      }
      if (url.includes("/handover-candidates")) {
        return jsonResponse({ items: [] });
      }
      throw new Error(`unexpected ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onTaskRefresh = vi.fn();
    const user = userEvent.setup();
    const action = baseAction({ confirm_version: 1 });
    const { rerender, client } = (() => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const view = render(
        <QueryClientProvider client={client}>
          <HandoverActionPanel
            surface="portal"
            task={baseTask()}
            action={action}
            onTaskRefresh={onTaskRefresh}
            onActionReplace={vi.fn()}
          />
        </QueryClientProvider>,
      );
      return { ...view, client };
    })();

    await user.click(screen.getByTestId("execute-handover"));
    await user.click(await screen.findByTestId("execute-confirm"));

    await waitFor(() => {
      expect(onTaskRefresh).toHaveBeenCalled();
    });
    expect(screen.queryByTestId("execute-confirm")).not.toBeInTheDocument();
    expect(screen.getByText("分配已更新，请重新确认后再执行。")).toBeVisible();
    // 旧 confirm_version 仍在时执行按钮保持禁用，防止连点再 409
    expect(screen.getByTestId("execute-handover")).toBeDisabled();

    rerender(
      <QueryClientProvider client={client}>
        <HandoverActionPanel
          surface="portal"
          task={baseTask()}
          action={baseAction({ confirm_version: 2 })}
          onTaskRefresh={onTaskRefresh}
          onActionReplace={vi.fn()}
        />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("execute-handover")).toBeEnabled();
    });
  });
});
