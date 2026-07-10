import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { HandoverTaskDetail } from "./HandoverTaskDetail";

const DETAIL_PAYLOAD = {
  handover_task: {
    id: 1,
    kind: "offboard",
    status: "in_progress",
    subject: {
      user_id: "u-1",
      name: "张三",
      email: "zhangsan@example.com",
      department: "销售部",
      status: "departed",
    },
    reason: "离职",
    created_by: "admin",
    created_at: "2026-07-01T09:00:00Z",
    updated_at: "2026-07-01T09:00:00Z",
    app_actions: [
      {
        id: 11,
        app_key: "easytrade",
        app_name: "EasyTrade",
        status: "done",
        to_user: { user_id: "u-9", name: "王五" },
        policy: {},
        preview_payload: {},
        result_payload: {},
        attempts: 1,
        last_error: "",
      },
      {
        id: 12,
        app_key: "crm",
        app_name: "CRM",
        status: "pending",
        to_user: null,
        policy: {},
        preview_payload: {},
        result_payload: {},
        attempts: 0,
        last_error: "",
      },
      {
        id: 13,
        app_key: "wiki",
        app_name: "Wiki",
        status: "failed",
        to_user: { user_id: "u-9", name: "王五" },
        policy: {},
        preview_payload: {},
        result_payload: {},
        attempts: 2,
        last_error: "下游服务超时",
      },
      {
        id: 14,
        app_key: "docs",
        app_name: "文档中心",
        status: "async_pending",
        to_user: { user_id: "u-9", name: "王五" },
        policy: {},
        preview_payload: {},
        result_payload: {},
        async_status_url: "https://docs.example.com/handover/status/14",
        async_poll_attempts: 2,
        attempts: 1,
        last_error: "",
      },
    ],
    team_items: [],
    transfer_plan: null,
  },
};

const GRANT_ITEMS_PAYLOAD = {
  data: [
    {
      id: 21,
      app_key: "crm",
      kind: "permission",
      key: "customer.view",
      name: "查看客户",
      scope_key: "GLOBAL",
      grant_type: "permanent",
      grant_expires_at: null,
      selected: true,
      status: "pending",
    },
  ],
};

function buildFetchMock() {
  return vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url === "/console/api/v1/lifecycle/handover-tasks/1/grant-items") {
      return jsonResponse(GRANT_ITEMS_PAYLOAD);
    }
    if (url === "/console/api/v1/lifecycle/handover-tasks/1") {
      return jsonResponse(DETAIL_PAYLOAD);
    }
    if (url === "/console/api/v1/lifecycle/handover-tasks/1/actions/crm/preview" && method === "POST") {
      return jsonResponse({
        app_action: {
          ...DETAIL_PAYLOAD.handover_task.app_actions[1],
          status: "previewed",
          preview_payload: { assets: [{ type: "customer", count: 23, label: "个客户" }] },
        },
      });
    }
    if (url === "/console/api/v1/lifecycle/handover-tasks/1/actions/wiki/preview" && method === "POST") {
      return jsonResponse({
        app_action: {
          ...DETAIL_PAYLOAD.handover_task.app_actions[2],
          status: "previewed",
          preview_payload: { assets: [], hook: "skipped" },
        },
      });
    }
    if (url === "/console/api/v1/lifecycle/handover-tasks/1/actions/docs/retry" && method === "POST") {
      return jsonResponse({
        app_action: {
          ...DETAIL_PAYLOAD.handover_task.app_actions[3],
          status: "done",
          async_status_url: "",
          async_poll_attempts: 3,
        },
      });
    }
    if (url.startsWith("/console/api/v1/user-options?q=")) {
      return jsonResponse({ data: [] });
    }
    throw new Error(`Unexpected fetch: ${method} ${url}`);
  });
}

describe("HandoverTaskDetail", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("工单总览与应用状态卡使用业务语言描述各应用进度", async () => {
    vi.stubGlobal("fetch", buildFetchMock());

    renderDetail();

    expect(await screen.findByText("离职交接 · 张三")).toBeVisible();
    // 已交接卡: 一句人话 + 状态徽标。
    expect(screen.getByText("已交接给 王五")).toBeVisible();
    // 待交接卡: 空状态文案不带告警语气。
    expect(screen.getByText("暂未指定接收人，数据保持原状，可稍后处理")).toBeVisible();
    // 失败卡: 一句人话失败原因 + 重试按钮; 技术细节收进「详情」。
    expect(screen.getAllByText("下游服务超时").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "重试" })).toBeVisible();
    expect(screen.getByText("等待下游处理")).toHaveClass("text-amber");
    expect(screen.getByText("下游系统正在处理，可查询最新状态")).toBeVisible();
    expect(screen.getByRole("button", { name: "查询状态" })).toBeVisible();
    expect(screen.getAllByText("详情").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "取消交接单" })).toBeVisible();
    expect(screen.getByRole("button", { name: "继续交接" })).toBeVisible();
  });

  test("异步处理中可通过现有重试端点查询最新状态", async () => {
    const fetchMock = buildFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderDetail();

    await user.click(await screen.findByRole("button", { name: "查询状态" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/lifecycle/handover-tasks/1/actions/docs/retry",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  test("向导选应用与选接收人: 统一接收人应用到所选应用后保存", async () => {
    const fetchMock = buildFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderDetail();

    await user.click(await screen.findByRole("button", { name: "继续交接" }));
    const dialog = await screen.findByRole("dialog");
    // 第一步只列出待处理(待交接/交接失败)的应用, 已交接的 EasyTrade 不出现。
    expect(within(dialog).getByText("CRM")).toBeVisible();
    expect(within(dialog).getByText("Wiki")).toBeVisible();
    expect(within(dialog).queryByText("EasyTrade")).toBeNull();
    expect(within(dialog).getByText("已选 2 个应用")).toBeVisible();

    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    fireEvent.change(within(dialog).getByRole("combobox", { name: "统一接收人" }), { target: { value: "u-9" } });
    await user.click(within(dialog).getByRole("button", { name: "应用到所选应用" }));
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/console/api/v1/lifecycle/handover-tasks/1" && init?.method === "PATCH",
      );
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({
        app_actions: [
          { app_key: "crm", to_user_id: "u-9", release_to_pool: false },
          { app_key: "wiki", to_user_id: "u-9", release_to_pool: false },
        ],
      });
    });
    // 保存成功后进入选权限步。
    expect(await within(dialog).findByText("查看客户")).toBeVisible();
  });

  test("向导选权限与预览数据: 保存勾选后逐应用生成预览", async () => {
    const fetchMock = buildFetchMock();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderDetail();

    await user.click(await screen.findByRole("button", { name: "继续交接" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "下一步" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));

    // 选权限步: 默认全选, 取消勾选后保存。
    const grantCheckbox = await within(dialog).findByRole("checkbox", { name: /查看客户/ });
    expect(grantCheckbox).toBeChecked();
    await user.click(grantCheckbox);
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        ([input, init]) =>
          String(input) === "/console/api/v1/lifecycle/handover-tasks/1/grant-items" && init?.method === "PATCH",
      );
      expect(JSON.parse(String(patchCall?.[1]?.body))).toEqual({ items: [{ id: 21, selected: false }] });
    });

    // 预览数据步: 有数据的应用展示格式化资产, 无钩子的应用提示无需数据交接。
    expect(await within(dialog).findByText(/23 个客户/)).toBeVisible();
    expect(await within(dialog).findByText("该应用无需数据交接。")).toBeVisible();
  });

  test("权限清单加载失败或预览失败时不能进入下一步", async () => {
    const baseFetch = buildFetchMock();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/console/api/v1/lifecycle/handover-tasks/1/actions/wiki/preview") {
        return jsonResponse({ error: { message: "Wiki 预览失败" } }, 422);
      }
      return baseFetch(input, init);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderDetail();

    await user.click(await screen.findByRole("button", { name: "继续交接" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    expect(await within(dialog).findByText("查看客户")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));

    expect(await within(dialog).findByRole("button", { name: "重新预览" })).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "下一步" })).toBeDisabled();
  });

  test("执行期间拒绝关闭，异步受理后查询状态才标记完成", async () => {
    const baseFetch = buildFetchMock();
    let releaseFirstExecute: (() => void) | undefined;
    let executionStarted = false;
    let detailReadAfterExecute = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/actions/crm/execute") && method === "POST") {
        await new Promise<void>((resolve) => {
          releaseFirstExecute = resolve;
        });
        executionStarted = true;
        return jsonResponse({
          app_action: {
            ...DETAIL_PAYLOAD.handover_task.app_actions[1],
            status: "async_pending",
            async_status_url: "https://crm.example.com/handover/status/12",
            async_poll_attempts: 0,
          },
        });
      }
      if (url.endsWith("/actions/wiki/execute") && method === "POST") {
        return jsonResponse({ app_action: { ...DETAIL_PAYLOAD.handover_task.app_actions[2], status: "done" } });
      }
      if (url.endsWith("/actions/crm/retry") && method === "POST") {
        return jsonResponse({
          app_action: {
            ...DETAIL_PAYLOAD.handover_task.app_actions[1],
            status: "done",
            async_status_url: "",
            async_poll_attempts: 1,
          },
        });
      }
      if (url === "/console/api/v1/lifecycle/handover-tasks/1" && method === "GET" && executionStarted) {
        detailReadAfterExecute += 1;
        return jsonResponse({
          handover_task: {
            ...DETAIL_PAYLOAD.handover_task,
            status: "completed",
            app_actions: DETAIL_PAYLOAD.handover_task.app_actions.map((action) => ({ ...action, status: "done" })),
          },
        });
      }
      return baseFetch(input, init);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderDetail();

    await user.click(await screen.findByRole("button", { name: "继续交接" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    expect(await within(dialog).findByText("查看客户")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "下一步" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "下一步" }));
    await user.click(within(dialog).getByRole("button", { name: "执行交接" }));

    await waitFor(() => expect(releaseFirstExecute).toBeDefined());
    await user.click(within(dialog).getByRole("button", { name: "关闭弹窗" }));
    expect(screen.getByRole("dialog")).toBeVisible();

    releaseFirstExecute?.();
    await waitFor(() => expect(detailReadAfterExecute).toBeGreaterThan(0));
    expect(await within(dialog).findByText("等待下游处理")).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "完成" })).toBeNull();
    expect(within(dialog).getByRole("button", { name: "执行交接" })).toBeDisabled();

    await user.click(within(dialog).getByRole("button", { name: "查询状态" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/lifecycle/handover-tasks/1/actions/crm/retry",
        expect.objectContaining({ method: "POST", body: "{}" }),
      );
    });
    expect(await within(dialog).findByRole("button", { name: "完成" })).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: "查询状态" })).toBeNull();
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) => String(input).endsWith("/actions/crm/execute") && init?.method === "POST",
      ),
    ).toHaveLength(1);
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) => String(input).endsWith("/actions/crm/retry") && init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  test("已取消转岗单的方案与待处理团队均为只读", async () => {
    const baseFetch = buildFetchMock();
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === "/console/api/v1/lifecycle/onboarding-templates") {
        return jsonResponse({
          data: [{ id: 8, name: "销售岗位", description: "", is_active: true, items: [] }],
        });
      }
      if (url === "/console/api/v1/lifecycle/handover-tasks/1") {
        return jsonResponse({
          handover_task: {
            ...DETAIL_PAYLOAD.handover_task,
            kind: "transfer",
            status: "cancelled",
            transfer_plan: {
              template_id: 8,
              template_name: "销售岗位",
              grant_diff: {
                revoke: [{ key: "crm:permission:customer.view:GLOBAL", selected: true }],
                add: [],
                keep: [],
              },
              confirmed_at: null,
            },
            team_items: [
              {
                id: 31,
                team_id: 3,
                team_name: "销售一组",
                action: "pending",
                to_user: null,
                status: "pending",
              },
            ],
          },
        });
      }
      return baseFetch(input, init);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderDetail();

    expect(await screen.findByRole("combobox", { name: "岗位模板" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /customer.view/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "确认调整" })).toBeNull();
    expect(screen.getByRole("combobox", { name: "销售一组 操作" })).toBeDisabled();
    expect(screen.queryByRole("combobox", { name: "销售一组 接任负责人" })).toBeNull();
  });
});

function renderDetail() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/lifecycle/handover-tasks/1"]}>
        <Routes>
          <Route path="/console/lifecycle/handover-tasks/:taskId" element={<HandoverTaskDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
