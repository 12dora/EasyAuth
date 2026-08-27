import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { PortalApprovalsSection } from "./PortalApprovalsSection";
import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  renderWithAntd,
  sortByColumn,
} from "../../../components/antd/testing";

// antd Table 在 jsdom 里每次筛选/排序/翻页都要重建整棵表格, 比自研原语慢得多,
// 整套用例并行跑时默认 5s 不够; 这里只放宽本文件的用例超时。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const PENDING_LIST_URL = "/portal/api/v1/me/approvals?status=pending&page=1&page_size=20";
const PROCESSED_LIST_URL = "/portal/api/v1/me/approvals?status=processed&page=1&page_size=20";
const PENDING_DETAIL_URL = "/portal/api/v1/me/approvals/42";

const pendingApproval = {
  id: 42,
  app_key: "crm",
  app_name: "CRM",
  request_type: "grant",
  base_grant_id: null,
  base_grant_revision: null,
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

  test("审批 tabs 使用方向键 roving tabindex 切换", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input) => {
        if (String(input) === PENDING_LIST_URL) {
          return pendingListResponse();
        }
        if (String(input) === PROCESSED_LIST_URL) {
          return jsonResponse({ data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } });
        }
        throw new Error(`Unexpected fetch: ${String(input)}`);
      }),
    );

    renderSection();

    const pendingTab = await screen.findByRole("tab", { name: "待办" });
    const processedTab = screen.getByRole("tab", { name: "已处理" });
    expect(pendingTab).toHaveAttribute("tabindex", "0");
    expect(processedTab).toHaveAttribute("tabindex", "-1");

    pendingTab.focus();
    await user.keyboard("{ArrowRight}");

    await waitFor(() => expect(processedTab).toHaveFocus());
    expect(processedTab).toHaveAttribute("aria-selected", "true");
    expect(processedTab).toHaveAttribute("tabindex", "0");
    expect(pendingTab).toHaveAttribute("tabindex", "-1");
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
        return jsonResponse({ approval: { ...pendingApproval, status: "grant_applied" } });
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
    const successNotice = await screen.findByRole("status");
    expect(successNotice).toHaveTextContent("授权已生效");
    expect(successNotice).toHaveAttribute("aria-live", "polite");
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

    expect(await screen.findByRole("alert")).toHaveTextContent("该申请已被其他审批人处理");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
  });

  test("base revision 409 时提示重新提交申请并刷新列表", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse({
          ...pendingApproval,
          request_type: "change",
          base_grant_id: 7,
          base_grant_revision: 3,
        });
      }
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return jsonResponse(
          {
            error: {
              code: "CONFLICT",
              message: "基础授权已变化, 请重新提交申请。",
              details: {
                decision_committed: true,
                reason: "base_grant_revision_conflict",
                status: "grant_conflict",
              },
            },
          },
          409,
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

    expect(await screen.findByRole("alert")).toHaveTextContent("授权事实已变化，请重新提交申请");
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

  test("同一审批重开时强制刷新详情，刷新中或失败均不得复用旧 submitted 事实", async () => {
    let detailCalls = 0;
    let rejectSecondDetail!: (reason: Error) => void;
    const secondDetail = new Promise<Response>((_resolve, reject) => {
      rejectSecondDetail = reject;
    });
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === PENDING_LIST_URL) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL) {
        detailCalls += 1;
        return detailCalls === 1 ? pendingDetailResponse() : secondDetail;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection(30_000);
    await user.click(await screen.findByRole("button", { name: "同意" }));
    let dialog = screen.getByRole("dialog", { name: "同意申请" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeEnabled());
    await user.click(within(dialog).getByRole("button", { name: "取消" }));

    await user.click(screen.getByRole("button", { name: "同意" }));
    dialog = screen.getByRole("dialog", { name: "同意申请" });
    expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeDisabled();
    expect(detailCalls).toBe(2);

    rejectSecondDetail(new Error("最新详情不可用"));
    expect(await within(dialog).findByText("申请详情加载失败，当前禁止审批。")).toBeVisible();
    expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/portal/api/v1/me/approvals/42/approve",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test.each([
    {
      status: "grant_failed",
      title: "审批已通过，但授权未落地",
      description: "请联系管理员重试授权落地",
    },
    {
      status: "grant_expired",
      title: "授权期限已过",
      description: "",
    },
  ])(
    "决定已提交且进入 $status 时关闭弹窗、刷新列表并展示准确终态",
    async ({ status, title, description }) => {
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
                  status,
                  approval: {
                    ...pendingApproval,
                    status,
                    decision_comment: "同意",
                    decided_at: "2026-07-10T08:00:00Z",
                    decided_by: "me",
                  },
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

      const notice = await screen.findByRole("alert");
      expect(notice).toHaveTextContent(title);
      if (description) {
        expect(notice).toHaveTextContent(description);
      }
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      await waitFor(() => {
        expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
      });
    },
  );

  test("提交事件到 pending 重渲染前同步禁止 Escape 和遮罩关闭", async () => {
    let resolveApproval!: (response: Response) => void;
    const approvalResponse = new Promise<Response>((resolve) => {
      resolveApproval = resolve;
    });
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === PENDING_LIST_URL && !init?.method) {
        return pendingListResponse();
      }
      if (url === PENDING_DETAIL_URL && !init?.method) {
        return pendingDetailResponse();
      }
      if (url === "/portal/api/v1/me/approvals/42/approve" && init?.method === "POST") {
        return approvalResponse;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();
    await user.click(await screen.findByRole("button", { name: "同意" }));
    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "确认同意" })).toBeEnabled());

    fireEvent.submit(document.getElementById("approval-decision-form")!);
    fireEvent.keyDown(document, { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "关闭弹窗遮罩" }));
    expect(dialog).toBeVisible();

    resolveApproval(jsonResponse({ approval: { ...pendingApproval, status: "grant_applied" } }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
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
    // antd 的区间文案按 page/page_size 推算, 不按当前页实际行数收窄。
    expect(await screen.findByText("第 1-20 条 / 共 21 条")).toBeVisible();
    await user.click(screen.getByTitle("下一页"));

    await waitFor(() => expect(fetchMock.mock.calls.some(([input]) => String(input) === pageTwoUrl)).toBe(true));
    expect(await screen.findByText("第 1-1 条 / 共 1 条")).toBeVisible();
    expect(screen.getByTitle("下一页")).toHaveClass("ant-pagination-disabled");
    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([input]) => String(input) === PENDING_LIST_URL).length).toBeGreaterThan(1);
    });
  });

  test("表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (!url.startsWith("/portal/api/v1/me/approvals?")) {
        throw new Error(`Unexpected fetch: ${url}`);
      }
      const page = new URLSearchParams(url.split("?")[1]).get("page") ?? "1";
      return jsonResponse({
        data: [
          {
            ...pendingApproval,
            id: Number(page),
            applicant: { ...pendingApproval.applicant, user_id: `u-${page}`, name: `申请人${page}` },
          },
        ],
        pagination: { page: Number(page), page_size: 20, total_items: 21, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();

    // 表格不设默认排序: 首屏不带 ordering, 表头也没有指示器。
    expect(await screen.findByText("申请人1")).toBeVisible();
    expect(columnSortOrder("提交时间")).toBeNull();

    await user.click(screen.getByTitle("下一页"));
    await screen.findByText("申请人2");

    await sortByColumn(user, "申请人");
    await waitFor(() =>
      expect(lastApprovalsUrl(fetchMock)).toBe(
        "/portal/api/v1/me/approvals?status=pending&page=1&page_size=20&ordering=applicant",
      ),
    );
    expect(columnSortOrder("申请人")).toBe("ascend");
    expect(columnSortOrder("提交时间")).toBeNull();

    await sortByColumn(user, "申请人");
    await waitFor(() =>
      expect(lastApprovalsUrl(fetchMock)).toBe(
        "/portal/api/v1/me/approvals?status=pending&page=1&page_size=20&ordering=-applicant",
      ),
    );
    expect(columnSortOrder("申请人")).toBe("descend");
  });

  test("切到已处理页签时清掉表头排序, 顺序交回后端默认序", async () => {
    const sortedPendingUrl = "/portal/api/v1/me/approvals?status=pending&page=1&page_size=20&ordering=applicant";
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === PENDING_LIST_URL || url === sortedPendingUrl) {
        return pendingListResponse();
      }
      if (url === PROCESSED_LIST_URL) {
        return jsonResponse({
          data: [{ ...pendingApproval, status: "grant_applied", status_label: "已授权", decided_at: "2026-07-02T09:00:00Z" }],
          pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderSection();
    await screen.findByText("张三");

    // 先在待办页签排一次序, 才看得出切页签是「清掉排序」而不是「本来就没排序」。
    await sortByColumn(user, "申请人");
    await waitFor(() => expect(lastApprovalsUrl(fetchMock)).toBe(sortedPendingUrl));
    expect(columnSortOrder("申请人")).toBe("ascend");

    await user.click(screen.getByRole("tab", { name: "已处理" }));

    await waitFor(() => expect(lastApprovalsUrl(fetchMock)).toBe(PROCESSED_LIST_URL));
    expect(columnSortOrder("申请人")).toBeNull();
    expect(columnSortOrder("处理时间")).toBeNull();
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

function lastApprovalsUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/portal/api/v1/me/approvals?"))
    .at(-1);
}

function renderSection(staleTime = 0) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime },
      mutations: { retry: false },
    },
  });

  renderWithAntd(
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
