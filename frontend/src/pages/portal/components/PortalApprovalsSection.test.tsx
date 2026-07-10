import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PortalApprovalsSection } from "./PortalApprovalsSection";

const PENDING_LIST_URL = "/portal/api/v1/me/approvals?status=pending&page=1&page_size=20";
const PENDING_DETAIL_URL = "/portal/api/v1/me/approvals/42";

const pendingApproval = {
  id: 42,
  app_key: "crm",
  app_name: "CRM",
  request_type: "grant",
  status: "submitted",
  status_label: "待审批",
  grant_type: "permanent",
  grant_expires_at: null,
  reason: "处理跨部门工单",
  submitted_at: "2026-07-01T09:00:00Z",
  authorization_groups: [
    {
      key: "sales-reader",
      kind: "role",
      name: "销售只读",
      grants: [{ permission: "orders.list", permission_name: "订单列表", scope: "SELF" }],
    },
  ],
  direct_grants: [
    { permission: "orders.read", permission_name: "查看订单", scope: "SELF" },
    { permission: "orders.export", permission_name: "导出订单", scope: "SELF" },
  ],
  decided_at: null,
  decision_comment: null,
  applicant: { user_id: "u-1", name: "张三", email: "zhangsan@example.test", department: "销售部" },
  approver_user_ids: ["me"],
  decided_by: "",
};

function pendingListResponse() {
  return jsonResponse({
    data: [pendingApproval],
    pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
  });
}

function pendingDetailResponse(approval: Record<string, unknown> = pendingApproval) {
  return jsonResponse({ approval });
}

describe("PortalApprovalsSection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("待办列表展示申请人、应用、申请内容摘要、期限、提交时间、理由和操作按钮", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        if (String(input) === PENDING_LIST_URL) {
          return pendingListResponse();
        }
        throw new Error(`Unexpected fetch: ${String(input)}`);
      }),
    );

    renderSection();

    expect(await screen.findByText("张三")).toBeVisible();
    expect(screen.getByText("销售部")).toBeVisible();
    expect(screen.getByText("CRM")).toBeVisible();
    expect(screen.getByText(/销售只读/)).toBeVisible();
    expect(screen.getByText("订单列表 (orders.list) · SELF")).toBeVisible();
    expect(screen.getByText("查看订单 (orders.read) · SELF")).toBeVisible();
    expect(screen.getByText("长期")).toBeVisible();
    expect(screen.getByText("处理跨部门工单")).toBeVisible();
    expect(screen.getByRole("button", { name: "同意" })).toBeVisible();
    expect(screen.getByRole("button", { name: "驳回" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "待办" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "已处理" })).toHaveAttribute("aria-selected", "false");
  });

  test("待办列表为空时展示空状态文案", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } }),
      ),
    );

    renderSection();

    expect(await screen.findByText("暂无需要你审批的申请")).toBeVisible();
  });

  test("驳回意见必填: 未填写时不发请求, 填写后提交并提示已驳回", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse();
      }
      if (url === "/portal/api/v1/me/approvals/42/reject" && init?.method === "POST") {
        return jsonResponse({ approval: { ...pendingApproval, status: "rejected" } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();

    await user.click(await screen.findByRole("button", { name: "驳回" }));
    const dialog = screen.getByRole("dialog", { name: "驳回申请" });
    expect(within(dialog).getByLabelText("审批意见")).toBeVisible();
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认驳回" })).toBeEnabled());

    await user.click(within(dialog).getByRole("button", { name: "确认驳回" }));
    expect(within(dialog).getByText("请填写驳回意见")).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalledWith("/portal/api/v1/me/approvals/42/reject", expect.anything());

    await user.type(within(dialog).getByLabelText("审批意见"), "范围过大，请缩小权限");
    await user.click(within(dialog).getByRole("button", { name: "确认驳回" }));

    await waitFor(() => {
      const rejectCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/portal/api/v1/me/approvals/42/reject" && init?.method === "POST",
      );
      expect(JSON.parse(String(rejectCall?.[1]?.body))).toEqual({ comment: "范围过大，请缩小权限" });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("申请已驳回");
  });

  test("同意成功后提示授权已生效并刷新列表", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse();
      }
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return jsonResponse({ approval: { ...pendingApproval, status: "approved" } });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();

    await user.click(await screen.findByRole("button", { name: "同意" }));
    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeEnabled());
    expect(within(dialog).getByText(/销售只读/)).toBeVisible();
    expect(within(dialog).getByText("订单列表 (orders.list) · SELF")).toBeVisible();
    expect(within(dialog).getByText("查看订单 (orders.read) · SELF")).toBeVisible();
    expect(within(dialog).getByText("处理跨部门工单")).toBeVisible();
    await user.type(within(dialog).getByLabelText("审批意见"), "同意开通");
    await user.click(within(dialog).getByRole("button", { name: "确认同意" }));

    await waitFor(() => {
      const approveCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input) === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST",
      );
      expect(JSON.parse(String(approveCall?.[1]?.body))).toEqual({ comment: "同意开通" });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("授权已生效");
    // 成功后失效列表 query, 会重新拉取待办列表。
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
  });

  test("409 冲突时提示该申请已被其他审批人处理并刷新列表", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse();
      }
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return jsonResponse({ error: { code: "conflict", message: "已被处理" } }, 409);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();

    await user.click(await screen.findByRole("button", { name: "同意" }));
    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "确认同意" }));

    expect(await screen.findByRole("status")).toHaveTextContent("该申请已被其他审批人处理");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
  });

  test("审批前加载完整事实，详情失败时 fail-closed 禁止提交", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === PENDING_LIST_URL) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL) {
        return jsonResponse({ error: { code: "broken", message: "详情不可用" } }, 500);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();
    await user.click(await screen.findByRole("button", { name: "同意" }));

    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    expect(await within(dialog).findByText("申请详情加载失败，当前禁止审批。")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/portal/api/v1/me/approvals/42/approve",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("授权应用失败的复合结果关闭弹窗、刷新列表并明确提示重试落地", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse();
      }
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "SEMANTIC_VALIDATION_ERROR",
              message: "grant apply failed",
              details: {
                decision_committed: true,
                status: "grant_failed",
                approval: { ...pendingApproval, status: "grant_failed", decision_comment: "同意" },
              },
            },
          },
          422,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();
    await user.click(await screen.findByRole("button", { name: "同意" }));
    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "确认同意" }));

    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("审批已通过，但授权未落地");
    expect(notice).toHaveTextContent("请联系管理员重试授权落地");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
  });

  test.each([
    { payload: {} },
    { payload: { data: null, pagination: null } },
    {
      payload: {
        data: [{}],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      },
    },
    {
      payload: {
        data: [pendingApproval],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        unexpected: true,
      },
    },
    {
      payload: {
        data: [{ ...pendingApproval, submitted_at: "not-a-date" }],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      },
    },
  ])(
    "200 异常审批载荷进入错误态而非空列表: $payload",
    async ({ payload }) => {
      vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(payload)));

      renderSection();

      expect(await screen.findByText("审批列表加载失败")).toBeVisible();
      expect(screen.queryByText("暂无需要你审批的申请")).not.toBeInTheDocument();
    },
  );

  test("使用服务端总数并在服务端末页收缩时 clamp 页码", async () => {
    const pageTwoUrl = "/portal/api/v1/me/approvals?status=pending&page=2&page_size=20";
    let pageOneCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === PENDING_LIST_URL) {
        pageOneCalls += 1;
        return jsonResponse({
          data: [pendingApproval],
          pagination:
            pageOneCalls === 1
              ? { page: 1, page_size: 20, total_items: 21, total_pages: 2 }
              : { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      if (url === pageTwoUrl) {
        return jsonResponse({
          data: [pendingApproval],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();
    expect(await screen.findByText("第 1-1 条 / 共 21 条")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "下一页" }));

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === pageTwoUrl)).toBe(true));
    expect(await screen.findByText("1 / 1")).toBeVisible();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
  });

  test("已处理列表展示同意意见和限时授权的具体到期时间", async () => {
    const processedUrl = "/portal/api/v1/me/approvals?status=processed&page=1&page_size=20";
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url === PENDING_LIST_URL) {
          return pendingListResponse();
        }
        if (url === processedUrl) {
          return jsonResponse({
            data: [
              {
                ...pendingApproval,
                status: "grant_applied",
                status_label: "已授权",
                grant_type: "timed",
                grant_expires_at: "2026-08-15T10:30:00Z",
                decided_at: "2026-07-02T09:00:00Z",
                decision_comment: "同意限时开通",
                decided_by: "me",
              },
            ],
            pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
          });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    const user = userEvent.setup();

    renderSection();
    await user.click(await screen.findByRole("tab", { name: "已处理" }));

    expect(await screen.findByText("同意限时开通")).toBeVisible();
    expect(screen.getByText(/2026\/08\/15/)).toBeVisible();
  });

  test("详情已被处理时 fail-closed 并提示冲突", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        const url = String(input);
        if (url === PENDING_LIST_URL) {
          return pendingListResponse();
        }
        if (url === PENDING_DETAIL_URL) {
          return pendingDetailResponse({
            ...pendingApproval,
            status: "rejected",
            decided_at: "2026-07-02T09:00:00Z",
            decision_comment: "已由其他人驳回",
            decided_by: "other-approver",
          });
        }
        throw new Error(`Unexpected fetch: ${url}`);
      }),
    );
    const user = userEvent.setup();

    renderSection();
    await user.click(await screen.findByRole("button", { name: "同意" }));

    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    expect(await within(dialog).findByText("该申请已被其他审批人处理")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeDisabled();
  });

  test("不完整的决定已提交错误不得伪装成 grant_failed 复合结果", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse();
      }
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "SEMANTIC_VALIDATION_ERROR",
              message: "复合结果缺少最新审批事实",
              details: { decision_committed: true, status: "grant_failed" },
            },
          },
          422,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();
    await user.click(await screen.findByRole("button", { name: "同意" }));
    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "确认同意" }));

    expect(await within(dialog).findByText("复合结果缺少最新审批事实")).toBeVisible();
    expect(screen.queryByText("审批已通过，但授权未落地")).not.toBeInTheDocument();
  });
});

function renderSection() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <PortalApprovalsSection />
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
