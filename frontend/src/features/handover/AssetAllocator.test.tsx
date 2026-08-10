import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { HandoverAction } from "../../lib/domain";
import { AssetAllocator, countArrangedAssetTypes } from "./AssetAllocator";

function actionFixture(overrides: Partial<HandoverAction> = {}): HandoverAction {
  return {
    app_key: "easytrade",
    app_name: "EasyTrade",
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
        count: 187,
        detail_supported: true,
        releasable: true,
        default_action: "skip",
        default_to_user: null,
        override_count: 0,
      },
      {
        type: "order",
        label: "在途订单",
        count: 23,
        detail_supported: true,
        releasable: false,
        default_action: "skip",
        default_to_user: null,
        override_count: 0,
      },
      {
        type: "task",
        label: "未完成任务",
        count: 0,
        detail_supported: false,
        releasable: true,
        default_action: "skip",
        default_to_user: null,
        override_count: 0,
      },
    ],
    approval_instance_warning: null,
    grant_receiver: null,
    summary: null,
    data_completed_at: null,
    ...overrides,
  };
}

function renderAllocator(action = actionFixture()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AssetAllocator surface="portal" taskId={1} action={action} />
    </QueryClientProvider>,
  );
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("AssetAllocator", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("三选一切换；releasable=false 时释放禁用，transfer/skip 可用", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        asset_type: {
          type: "customer",
          label: "名下客户",
          count: 187,
          detail_supported: true,
          releasable: true,
          default_action: "release",
          default_to_user: null,
          override_count: 0,
        },
        confirm_version: 2,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAllocator();

    const customerRow = screen.getByTestId("asset-type-row-customer");
    const customerSelect = within(customerRow).getByLabelText(/默认处理方式/);
    expect(within(customerSelect).getByRole("option", { name: "全部释放为无主" })).toBeEnabled();

    const orderRow = screen.getByTestId("asset-type-row-order");
    const orderSelect = within(orderRow).getByLabelText(/默认处理方式/);
    expect(within(orderSelect).getByRole("option", { name: "全部释放为无主" })).toBeDisabled();
    expect(within(orderSelect).getByRole("option", { name: "全部转给…" })).toBeEnabled();
    expect(within(orderSelect).getByRole("option", { name: "暂不处理" })).toBeEnabled();

    // release 可立即 PATCH
    await user.selectOptions(customerSelect, "release");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/assets/customer"),
        expect.objectContaining({ method: "PATCH" }),
      );
    });
  });

  test("transfer 必选接收人：切换后先出选择器，未选人不 PATCH", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input).includes("/handover-candidates")) {
        return jsonResponse({
          items: [{ user_id: "u-9", name: "张某某", department: "销售" }],
        });
      }
      return jsonResponse({
        asset_type: {
          type: "customer",
          label: "名下客户",
          count: 187,
          detail_supported: true,
          releasable: true,
          default_action: "transfer",
          default_to_user: { user_id: "u-9", name: "张某某" },
          override_count: 0,
        },
        confirm_version: 2,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderAllocator();

    const customerRow = screen.getByTestId("asset-type-row-customer");
    const customerSelect = within(customerRow).getByLabelText(/默认处理方式/);

    await user.selectOptions(customerSelect, "transfer");

    // 选择器出现，但尚未 PATCH（无接收人）
    expect(await within(customerRow).findByLabelText(/接收人/)).toBeVisible();
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => String(input).includes("/assets/customer") && init?.method === "PATCH",
      ),
    ).toBe(false);

    // 选中接收人后才 PATCH
    const picker = within(customerRow).getByRole("combobox", { name: /接收人/ });
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: /张某某/ }));

    await waitFor(() => {
      const patchCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input).includes("/assets/customer") && init?.method === "PATCH",
      );
      expect(patchCall).toBeTruthy();
      const body = JSON.parse(String(patchCall?.[1]?.body));
      expect(body).toEqual({
        default_action: "transfer",
        default_to_user_id: "u-9",
      });
    });
  });

  test("已安排 N 类 / 共 M 类 计数", () => {
    const action = actionFixture({
      asset_types: [
        {
          type: "a",
          label: "A",
          count: 1,
          detail_supported: false,
          releasable: true,
          default_action: "transfer",
          default_to_user: { user_id: "u1", name: "张" },
          override_count: 0,
        },
        {
          type: "b",
          label: "B",
          count: 1,
          detail_supported: false,
          releasable: true,
          default_action: "skip",
          default_to_user: null,
          override_count: 2,
        },
        {
          type: "c",
          label: "C",
          count: 1,
          detail_supported: false,
          releasable: true,
          default_action: "skip",
          default_to_user: null,
          override_count: 0,
        },
      ],
    });
    renderAllocator(action);
    expect(screen.getByTestId("asset-allocator-progress")).toHaveTextContent("已安排 2 类 / 共 3 类");
    expect(countArrangedAssetTypes(action.asset_types)).toEqual({ arranged: 2, total: 3 });
  });

  test("override 改回默认自动移除；整体替换 payload 形状", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/overrides") && method === "GET") {
        return jsonResponse({
          overrides_version: 3,
          overrides: [
            {
              asset_id: "c1",
              action: "transfer",
              to_user: { user_id: "u-2", name: "李某某" },
              label: "客户1",
            },
          ],
        });
      }
      if (url.includes("/items?")) {
        return jsonResponse({
          items: [
            { id: "c1", label: "客户1", hint: "" },
            { id: "c2", label: "客户2", hint: "" },
          ],
          page: 1,
          page_size: 50,
          total: 2,
          unfiltered_total: 2,
          stale: false,
        });
      }
      if (url.endsWith("/overrides") && method === "PUT") {
        return jsonResponse({
          overrides_version: 4,
          confirm_version: 5,
          override_count: 0,
          dropped_invalid: 0,
        });
      }
      if (url.includes("/handover-candidates")) {
        return jsonResponse({
          items: [
            { user_id: "u-1", name: "张某某" },
            { user_id: "u-2", name: "李某某" },
          ],
        });
      }
      throw new Error(`unexpected ${method} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    const action = actionFixture({
      asset_types: [
        {
          type: "customer",
          label: "名下客户",
          count: 2,
          detail_supported: true,
          releasable: true,
          default_action: "transfer",
          default_to_user: { user_id: "u-1", name: "张某某" },
          override_count: 1,
        },
      ],
    });
    renderAllocator(action);

    await user.click(screen.getByRole("button", { name: "展开明细" }));
    expect(await screen.findByTestId("asset-item-c1")).toBeVisible();

    // 把 c1 从 override 接收人 李某某 改回默认 张某某 → 应从 PUT payload 中移除
    const item = screen.getByTestId("asset-item-c1");
    const picker = within(item).getByRole("combobox", { name: /接收人/ });
    await user.click(picker);
    await user.click(await screen.findByRole("option", { name: /张某某/ }));

    await user.click(screen.getByRole("button", { name: "保存单独指定" }));

    await waitFor(() => {
      const putCall = fetchMock.mock.calls.find(
        ([input, init]) => String(input).endsWith("/overrides") && init?.method === "PUT",
      );
      expect(putCall).toBeTruthy();
      const body = JSON.parse(String(putCall?.[1]?.body));
      expect(body).toEqual({
        overrides_version: 3,
        overrides: [],
      });
    });
  });
});
