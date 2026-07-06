import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PortalApprovalsSection } from "./PortalApprovalsSection";

const PENDING_LIST_URL = "/portal/api/v1/me/approvals?status=pending&page=1&page_size=20";

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
  authorization_groups: [{ key: "sales-reader", kind: "role", name: "销售只读" }],
  direct_grants: [
    { permission: "orders.read", permission_name: "查看订单", scope: "SELF" },
    { permission: "orders.export", permission_name: "导出订单", scope: "SELF" },
  ],
  decided_at: null,
  decision_comment: null,
  applicant: { user_id: "u-1", name: "张三", email: "zhangsan@example.test", department: "销售部" },
  approver_user_ids: ["me"],
  decided_by: null,
};

function pendingListResponse() {
  return jsonResponse({
    data: [pendingApproval],
    pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
  });
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
    expect(screen.getByText("销售只读、直接权限 2 项")).toBeVisible();
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
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return jsonResponse({ error: { code: "conflict", message: "已被处理" } }, 409);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();

    await user.click(await screen.findByRole("button", { name: "同意" }));
    await user.click(within(screen.getByRole("dialog", { name: "同意申请" })).getByRole("button", { name: "确认同意" }));

    expect(await screen.findByRole("status")).toHaveTextContent("该申请已被其他审批人处理");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
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
