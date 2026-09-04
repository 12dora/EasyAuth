import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import {
  ANTD_TEST_TIMEOUT_MS,
  columnSortOrder,
  renderWithAntd,
  sortByColumn,
} from "../../../components/antd/testing";
import { DESIGN_TOKENS } from "../../../components/antd/theme";
import { formatAppDisplayName } from "../../../lib/appDisplayName";

import { PortalRequestsSection } from "./PortalRequestsSection";

// antd Table 在 jsdom 里每次排序/翻页都要重建整棵表格, 整套用例并行跑时默认 5s 不够。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const REQUESTS_URL = "/portal/api/v1/me/access-requests?page=1&page_size=20";

function renderRequests() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  renderWithAntd(
    <QueryClientProvider client={client}>
      <PortalRequestsSection />
    </QueryClientProvider>,
  );
}

describe("PortalRequestsSection 表格", () => {
  test("状态列是按语义上色的纯文字, 既没有徽章也没有审批意见", async () => {
    stubRequests([
      requestRow({ id: 1, app_name: "已授权应用", status: "grant_applied", status_label: "授权已落库, 权限已生效" }),
      requestRow({ id: 2, app_name: "待审应用", status: "submitted", status_label: "等待审批" }),
      requestRow({
        id: 3,
        app_name: "驳回应用",
        status: "rejected",
        status_label: "已驳回",
        decision_comment: "权限范围过大",
        decided_at: "2026-07-02T10:00:00Z",
      }),
      requestRow({ id: 4, app_name: "冲突应用", status: "grant_conflict", status_label: "授权冲突" }),
      requestRow({ id: 5, app_name: "已撤回应用", status: "withdrawn", status_label: "已撤回" }),
    ]);

    try {
      renderRequests();

      // 列里用的是前端短标签, 后端那句长说明("授权已落库, 权限已生效")不进表格。
      expect(await screen.findByText("已生效")).toHaveStyle({ color: DESIGN_TOKENS.evergreen });
      expect(screen.queryByText("授权已落库, 权限已生效")).not.toBeInTheDocument();
      expect(screen.getByText("待审批")).toHaveStyle({ color: DESIGN_TOKENS.accent });
      expect(screen.getByText("已拒绝")).toHaveStyle({ color: DESIGN_TOKENS.signal });
      expect(screen.getByText("基础授权已变化")).toHaveStyle({ color: DESIGN_TOKENS.amber });
      expect(screen.getByText("已撤回")).toHaveStyle({ color: DESIGN_TOKENS.inkFaint });

      // 徽章会给状态套一层边框底色和等宽小字; 状态列现在只有文字。
      expect(screen.getByText("已生效")).not.toHaveClass("border", "font-mono");
      // 审批意见搬进了详情弹窗, 表格里不再有那一行小字。
      expect(screen.queryByText(/审批意见/)).not.toBeInTheDocument();
      expect(screen.queryByText(/权限范围过大/)).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("列只剩八列, 直接授权列已删除", async () => {
    stubRequests([requestRow({ app_name: "CRM" })]);

    try {
      renderRequests();
      await screen.findByText("CRM");

      const head = screen.getByRole("table", { name: "我的申请记录列表" }).querySelector("thead.ant-table-thead");
      const titles = [...(head?.querySelectorAll("th") ?? [])].map((cell) => cell.textContent?.trim());

      expect(titles).toEqual(["状态", "审批人", "应用", "权限组", "过期时间", "提交时间", "原因", "操作"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  /**
   * 列宽不变量。
   *
   * AppTable 固定 `tableLayout: "fixed"`, 列宽只认 `<colgroup>`: 没声明 width 的列只能去
   * 分摊 `scroll.x`(= minWidth) 减掉定宽列之后的剩余量。线上就是这么坏掉的 —— 定宽列之和
   * 逼近 minWidth 时剩余量趋近 0, 权限组 / 原因被压成一个字宽, 中文表头竖排成一列字。
   * 所以两件事必须一起锁住: 每列都声明宽度, 且 minWidth 恰好是它们的和。
   */
  test("每列都声明宽度, minWidth 等于列宽之和且能装进桌面宽度", async () => {
    stubRequests([requestRow({ app_name: "CRM" })]);

    try {
      renderRequests();
      await screen.findByText("CRM");

      const table = screen.getByRole("table", { name: "我的申请记录列表" });
      const widths = declaredColumnWidths(table);

      // 状态 / 审批人 / 应用 / 权限组 / 过期时间 / 提交时间 / 原因 / 操作。
      expect(widths).toEqual([100, 120, 150, 160, 130, 140, 170, 120]);
      expect(widths).toHaveLength(table.querySelectorAll("thead.ant-table-thead th").length);
      const total = widths.reduce((sum, width) => sum + width, 0);
      expect(tableScrollWidth(table)).toBe(total);
      // 「我的权限」是 940; 申请表多三列, 但仍要装得进常见的桌面正文宽度。
      expect(total).toBeLessThanOrEqual(1100);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("期限与过期时间合并成一列: 长期给标签, 限时给时刻", async () => {
    stubRequests([
      requestRow({ id: 1, app_name: "长期应用", grant_type: "permanent", grant_expires_at: null }),
      requestRow({ id: 2, app_name: "限时应用", grant_type: "timed", grant_expires_at: "2026-08-01T10:00:00Z" }),
    ]);

    try {
      renderRequests();
      await screen.findByText("长期应用");

      expect(cellText("长期应用", 4)).toBe("长期");
      expect(cellText("限时应用", 4)).toMatch(/^2026\/08\/01/);
      expect(screen.queryByRole("columnheader", { name: "期限" })).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("权限组列只给组名, 只有直接授权的申请给 -", async () => {
    stubRequests([
      requestRow({
        id: 1,
        app_name: "组申请",
        authorization_groups: [
          { key: "sales-reader", kind: "role", name: "销售只读" },
          { key: "orders-ops", kind: "bundle", name: "订单运维" },
        ],
      }),
      requestRow({
        id: 2,
        app_name: "直接授权申请",
        direct_grants: [{ permission: "orders.refund.approve", permission_name: "审批退款", scope: "TEAM" }],
      }),
    ]);

    try {
      renderRequests();
      await screen.findByText("组申请");

      expect(cellText("组申请", 3)).toBe("销售只读、订单运维");
      expect(screen.queryByText("销售只读 [角色]")).not.toBeInTheDocument();
      // 直接授权在详情弹窗里列, 表格里不再有这一列。
      expect(cellText("直接授权申请", 3)).toBe("-");
      expect(screen.queryByRole("columnheader", { name: "直接授权" })).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("审批人列: 待审批给当前审批人, 已决给决定人, 无姓名回退 actor id", async () => {
    stubRequests([
      requestRow({
        id: 1,
        app_name: "待审应用",
        status: "submitted",
        status_label: "等待审批",
        current_approvers: [
          { user_id: "manager-001", name: "张主管" },
          { user_id: "owner-002", name: "李负责人" },
        ],
      }),
      requestRow({
        id: 2,
        app_name: "已批准应用",
        status: "approved",
        status_label: "已批准",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
      }),
      requestRow({
        id: 3,
        app_name: "代审应用",
        status: "approved",
        status_label: "已批准",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
        decided_by: "console-admin-9",
        decision_actor_type: "console_admin",
        decided_by_name: null,
      }),
      requestRow({ id: 4, app_name: "已撤回应用", status: "withdrawn", status_label: "已撤回" }),
    ]);

    try {
      renderRequests();
      await screen.findByText("待审应用");

      expect(screen.getByRole("columnheader", { name: "审批人" })).toBeVisible();
      expect(cellText("待审应用", 1)).toBe("张主管、李负责人");
      expect(cellText("已批准应用", 1)).toBe("张主管");
      // 后端解析不出姓名时给 null, 前端展示 actor id 而不是空白。
      expect(cellText("代审应用", 1)).toBe("console-admin-9");
      expect(cellText("已撤回应用", 1)).toBe("-");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("应用列按「别名 + 技术名」展示", async () => {
    stubRequests([requestRow({ app_key: "easycustoms", app_name: "EasyCustoms", app_alias: "海关数据" })]);

    try {
      renderRequests();

      expect(
        await screen.findByText(formatAppDisplayName({ name: "EasyCustoms", alias: "海关数据" })),
      ).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("撤回按钮恒在: 只有等待审批可点, 其余行置灰并解释原因", async () => {
    stubRequests([
      requestRow({ id: 1, app_name: "待审应用", status: "submitted", status_label: "等待审批" }),
      requestRow({ id: 2, app_name: "已授权应用", status: "grant_applied", status_label: "已授权", applied_at: "2026-07-02T10:05:00Z" }),
    ]);
    const user = userEvent.setup();

    try {
      renderRequests();
      await screen.findByText("待审应用");

      const [pending, applied] = screen.getAllByRole("button", { name: "撤回" });
      expect(pending).toBeEnabled();
      expect(applied).toBeDisabled();

      await user.hover(applied);
      expect(await screen.findByRole("tooltip")).toHaveTextContent("只有等待审批的申请可以撤回");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("对 submitted 申请点撤回会调用撤回端点", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === REQUESTS_URL) {
        return jsonResponse(listPayload([requestRow({ id: 88, app_name: "CRM", status: "submitted", status_label: "已提交" })]));
      }
      if (url === "/portal/api/v1/me/access-requests/88/withdraw" && init?.method === "POST") {
        return jsonResponse({ access_request: requestRow({ id: 88, status: "withdrawn", status_label: "已撤回" }) });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderRequests();

      await screen.findByText("CRM");
      await userEvent.click(screen.getByRole("button", { name: "撤回" }));

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/portal/api/v1/me/access-requests/88/withdraw",
          expect.objectContaining({ method: "POST" }),
        ),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("表头排序是服务端排序: 带 ordering 请求、回到第 1 页, 指示器跟着走", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (!url.startsWith("/portal/api/v1/me/access-requests?")) {
        throw new Error(`Unexpected fetch: ${url}`);
      }
      const page = new URLSearchParams(url.split("?")[1]).get("page") ?? "1";
      return jsonResponse({
        data: [requestRow({ id: Number(page), app_key: `app-${page}`, app_name: `应用${page}` })],
        pagination: { page: Number(page), page_size: 20, total_items: 21, total_pages: 2 },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    try {
      renderRequests();

      // 表格不设默认排序: 首屏不带 ordering, 表头也没有指示器。
      expect(await screen.findByText("应用1")).toBeVisible();
      expect(columnSortOrder("提交时间")).toBeNull();

      await user.click(screen.getByTitle("下一页"));
      await screen.findByText("应用2");

      await sortByColumn(user, "状态");
      await waitFor(() =>
        expect(lastFetchUrl(fetchMock)).toBe("/portal/api/v1/me/access-requests?page=1&page_size=20&ordering=status"),
      );
      expect(columnSortOrder("状态")).toBe("ascend");
      expect(columnSortOrder("提交时间")).toBeNull();

      await sortByColumn(user, "状态");
      await waitFor(() =>
        expect(lastFetchUrl(fetchMock)).toBe("/portal/api/v1/me/access-requests?page=1&page_size=20&ordering=-status"),
      );
      expect(columnSortOrder("状态")).toBe("descend");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("使用服务端分页", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === REQUESTS_URL) {
        return jsonResponse({
          data: [requestRow({ id: 9, app_name: "CRM", reason: "处理工单" })],
          pagination: { page: 1, page_size: 20, total_items: 21, total_pages: 2 },
        });
      }
      if (url === "/portal/api/v1/me/access-requests?page=2&page_size=20") {
        return jsonResponse({
          data: [requestRow({ id: 21, app_key: "erp", app_name: "ERP", reason: "第二页申请" })],
          pagination: { page: 2, page_size: 20, total_items: 21, total_pages: 2 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      renderRequests();

      expect(await screen.findByText("处理工单")).toBeVisible();
      expect(screen.getByText("第 1-20 条 / 共 21 条")).toBeVisible();

      await userEvent.click(screen.getByTitle("下一页"));

      expect(await screen.findByText("ERP")).toBeVisible();
      expect(fetchMock).toHaveBeenCalledWith(
        "/portal/api/v1/me/access-requests?page=2&page_size=20",
        expect.anything(),
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("在 data 为 null 时明确报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async () =>
        jsonResponse({ data: null, pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } }),
      ),
    );

    try {
      renderRequests();

      expect(await screen.findByText("申请记录加载失败")).toBeVisible();
      expect(screen.getByText("申请记录列表响应格式无效：data 必须是数组")).toBeVisible();
      expect(screen.queryByText("暂无申请记录")).not.toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("缺少 app_alias 时明确报错", async () => {
    const row: Record<string, unknown> = requestRow();
    delete row.app_alias;
    stubRequests([row]);

    try {
      renderRequests();

      expect(await screen.findByText("申请记录加载失败")).toBeVisible();
      expect(screen.getByText("申请记录列表 data[0].app_alias 必须是字符串")).toBeVisible();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("PortalRequestsSection 详情弹窗", () => {
  test("摘要给出应用、权限组、直接授权、期限和原因", async () => {
    stubRequests([
      requestRow({
        app_name: "CRM",
        app_alias: "客户管理",
        reason: "处理退款工单",
        grant_type: "timed",
        grant_expires_at: "2026-08-01T10:00:00Z",
        authorization_groups: [{ key: "sales-reader", kind: "role", name: "销售只读" }],
        direct_grants: [
          { permission: "orders.refund.approve", permission_name: "审批退款", scope: "TEAM" },
          { permission: "orders.export", permission_name: "导出订单", scope: "ALL" },
        ],
      }),
    ]);

    try {
      await openDetail();

      // antd 的入场动画在 jsdom 里永远走不完(没有 transitionend), 弹窗内的节点始终带着
      // `ant-zoom-appear-prepare` 的 opacity: 0, 因此这里断言存在而不是可见。
      // antd 的入场动画在 jsdom 里永远走不完(没有 transitionend), 弹窗内的节点始终带着
      // `ant-zoom-appear-prepare` 的 opacity: 0, 因此这里断言存在而不是可见。
      const summary = summaryList();
      expect(within(summary).getByText(formatAppDisplayName({ name: "CRM", alias: "客户管理" }))).toBeInTheDocument();
      expect(within(summary).getByText("销售只读")).toBeInTheDocument();
      // 直接授权只在弹窗里展开, 格式是「权限名 · 范围」。
      expect(within(summary).getByText("审批退款 · TEAM")).toBeInTheDocument();
      expect(within(summary).getByText("导出订单 · ALL")).toBeInTheDocument();
      expect(within(summary).getByText("处理退款工单")).toBeInTheDocument();
      expect(within(summary).getByText(/^2026\/08\/01/)).toBeInTheDocument();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("等待审批: 审批节点在进行中并列出当前审批人, 权限生效还没走到", async () => {
    stubRequests([
      requestRow({
        status: "submitted",
        status_label: "等待审批",
        current_approvers: [
          { user_id: "manager-001", name: "张主管" },
          { user_id: "owner-002", name: "李负责人" },
        ],
      }),
    ]);

    try {
      await openDetail();

      expect(stepStatus("提交申请")).toBe("finish");
      expect(stepDescription("提交申请")).toMatch(/^2026\/07\/01/);
      expect(stepStatus("审批")).toBe("process");
      expect(stepDescription("审批")).toBe("张主管、李负责人");
      expect(stepStatus("权限生效")).toBe("wait");
      // 长期授权没有到期这一步。
      expect(stepTitles()).toEqual(["提交申请", "审批", "权限生效"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("已批准未生效: 审批节点给决定人、时间和审批意见, 权限生效仍在等待", async () => {
    stubRequests([
      requestRow({
        status: "approved",
        status_label: "已批准",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
        decision_comment: "同意按期开放",
      }),
    ]);

    try {
      await openDetail();

      expect(stepStatus("审批")).toBe("finish");
      expect(stepDescription("审批")).toContain("张主管");
      expect(stepDescription("审批")).toMatch(/2026\/07\/02/);
      expect(stepDescription("审批")).toContain("审批意见：同意按期开放");
      expect(stepStatus("权限生效")).toBe("wait");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("已驳回: 审批节点是错误态并保留驳回理由", async () => {
    stubRequests([
      requestRow({
        status: "rejected",
        status_label: "已驳回",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
        decided_at: "2026-07-02T10:00:00Z",
        decision_comment: "权限范围过大",
      }),
    ]);

    try {
      await openDetail();

      expect(stepStatus("审批")).toBe("error");
      expect(stepDescription("审批")).toContain("权限范围过大");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("已授权的限时申请: 生效节点给生效时刻, 并多出一个尚未到达的到期节点", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-07-10T00:00:00Z") });
    stubRequests([
      requestRow({
        status: "grant_applied",
        status_label: "已授权",
        grant_type: "timed",
        grant_expires_at: "2026-08-01T10:00:00Z",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
        applied_at: "2026-07-02T10:05:00Z",
      }),
    ]);

    try {
      await openDetail();

      expect(stepTitles()).toEqual(["提交申请", "审批", "权限生效", "到期"]);
      expect(stepStatus("权限生效")).toBe("finish");
      expect(stepDescription("权限生效")).toMatch(/^2026\/07\/02/);
      expect(stepStatus("到期")).toBe("wait");
      expect(stepDescription("到期")).toMatch(/^2026\/08\/01/);
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  test("限时授权的到期时刻已过: 到期节点走完", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-09-01T00:00:00Z") });
    stubRequests([
      requestRow({
        status: "grant_applied",
        status_label: "已授权",
        grant_type: "timed",
        grant_expires_at: "2026-08-01T10:00:00Z",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
        applied_at: "2026-07-02T10:05:00Z",
      }),
    ]);

    try {
      await openDetail();

      expect(stepStatus("权限生效")).toBe("finish");
      expect(stepStatus("到期")).toBe("finish");
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });

  test("授权期限已过未应用: 生效节点是错误态, 不再挂到期节点", async () => {
    stubRequests([
      requestRow({
        status: "grant_expired",
        status_label: "授权期限已过, 未应用",
        grant_type: "timed",
        grant_expires_at: "2026-08-01T10:00:00Z",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
      }),
    ]);

    try {
      await openDetail();

      expect(stepTitles()).toEqual(["提交申请", "审批", "权限生效"]);
      expect(stepStatus("权限生效")).toBe("error");
      expect(stepDescription("权限生效")).toBe("授权期限已过, 未应用");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("授权失败: 生效节点是错误态并给出后端状态文案", async () => {
    stubRequests([
      requestRow({
        status: "grant_failed",
        status_label: "授权失败",
        decided_by: "manager-001",
        decision_actor_type: "user",
        decided_by_name: "张主管",
        decided_at: "2026-07-02T10:00:00Z",
        approved_at: "2026-07-02T10:00:00Z",
      }),
    ]);

    try {
      await openDetail();

      expect(stepStatus("审批")).toBe("finish");
      expect(stepStatus("权限生效")).toBe("error");
      expect(stepDescription("权限生效")).toBe("授权失败");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  test("已撤回: 审批节点整个换成已撤回", async () => {
    stubRequests([
      requestRow({ status: "withdrawn", status_label: "已撤回", withdrawn_at: "2026-07-03T09:00:00Z" }),
    ]);

    try {
      await openDetail();

      expect(stepTitles()).toEqual(["提交申请", "已撤回", "权限生效"]);
      expect(stepStatus("已撤回")).toBe("finish");
      expect(stepDescription("已撤回")).toMatch(/^2026\/07\/03/);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

/* ------------------------------------------------------------------ */
/* 测试脚手架                                                          */
/* ------------------------------------------------------------------ */

/** 渲染表格, 点开第一行的「详情」, 等弹窗出现。 */
async function openDetail() {
  renderRequests();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "详情" }));
  await screen.findByText("申请详情");
}

/** 弹窗上半部的申请内容摘要(下半部是流程图, 两处都会出现到期时刻)。 */
function summaryList(): HTMLElement {
  const list = screen.getByRole("dialog").querySelector("dl");
  if (!(list instanceof HTMLElement)) {
    throw new Error("详情弹窗里没有申请内容摘要");
  }
  return list;
}

const STEP_STATUSES = ["finish", "process", "wait", "error"] as const;

function stepNodes(): HTMLElement[] {
  return [...screen.getByRole("dialog").querySelectorAll<HTMLElement>(".ant-steps-item")];
}

function stepTitles(): string[] {
  return stepNodes().map((item) => item.querySelector(".ant-steps-item-title")?.textContent?.trim() ?? "");
}

function stepNode(title: string): HTMLElement {
  const node = stepNodes().find(
    (item) => item.querySelector(".ant-steps-item-title")?.textContent?.trim() === title,
  );
  if (!node) {
    throw new Error(`流程图里没有「${title}」节点, 现有节点: ${stepTitles().join(" | ")}`);
  }
  return node;
}

function stepStatus(title: string): string {
  const node = stepNode(title);
  const status = STEP_STATUSES.find((candidate) => node.classList.contains(`ant-steps-item-${candidate}`));
  if (!status) {
    throw new Error(`节点「${title}」没有 antd 的状态 class, 实际为 ${node.className}`);
  }
  return status;
}

function stepDescription(title: string): string {
  return stepNode(title).querySelector(".ant-steps-item-description")?.textContent?.trim() ?? "";
}

function requestRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    app_key: "crm",
    app_name: "CRM",
    app_alias: "",
    request_type: "grant",
    base_grant_id: null,
    base_grant_revision: null,
    status: "submitted",
    status_label: "等待审批",
    grant_type: "permanent",
    grant_expires_at: null,
    reason: "申请权限",
    submitted_at: "2026-07-01T10:00:00Z",
    authorization_groups: [],
    direct_grants: [],
    current_approvers: [],
    decided_by: "",
    decision_actor_type: "",
    decided_by_name: null,
    decided_at: null,
    decision_comment: "",
    approved_at: null,
    applied_at: null,
    withdrawn_at: null,
    ...overrides,
  };
}

function listPayload(rows: Record<string, unknown>[]) {
  return {
    data: rows,
    pagination: { page: 1, page_size: 20, total_items: rows.length, total_pages: 1 },
  };
}

function stubRequests(rows: Record<string, unknown>[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url !== REQUESTS_URL) {
        throw new Error(`Unexpected fetch: ${url}`);
      }
      return jsonResponse(listPayload(rows));
    }),
  );
}

/** 某个应用所在行的第 index 个单元格文本(列序: 状态/审批人/应用/权限组/过期时间/提交时间/原因/操作)。 */
function cellText(appName: string, index: number): string {
  const row = screen.getByText(appName).closest("tr");
  if (row === null) {
    throw new Error(`未找到应用 ${appName} 所在的表格行`);
  }
  return within(row).getAllByRole("cell")[index].textContent ?? "";
}

/**
 * 表格 `<colgroup>` 里各列声明的像素宽度, 按列序返回。
 *
 * 列上没写 width 时 rc-table 渲染出的 `<col>` 不带 `style.width`, 这里直接抛错 ——
 * 「每列都声明了宽度」正是要锁住的不变量, 不能悄悄按 0 计入求和。
 */
function declaredColumnWidths(table: HTMLElement): number[] {
  return [...table.querySelectorAll<HTMLTableColElement>("colgroup > col")].map((col, index) => {
    const width = col.style.width;
    if (!width.endsWith("px")) {
      throw new Error(`第 ${index + 1} 列没有声明像素列宽, 实际为 ${JSON.stringify(width)}`);
    }
    return Number.parseFloat(width);
  });
}

/** AppTable 传下去的 minWidth(即 `scroll.x`)由 rc-table 写在滚动 `<table>` 的内联 width 上。 */
function tableScrollWidth(table: HTMLElement): number {
  const width = table.style.width;
  if (!width.endsWith("px")) {
    throw new Error(`表格没有把 minWidth 写成像素宽度, 实际为 ${JSON.stringify(width)}`);
  }
  return Number.parseFloat(width);
}

function lastFetchUrl(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return String(fetchMock.mock.calls.at(-1)?.[0] ?? "");
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
