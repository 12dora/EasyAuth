import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ToastProvider } from "../../components/ui/Toast";
import { ApprovalInstancesPage } from "./ApprovalInstancesPage";

const LIST_URL = "/console/api/v1/operations/approval-instances?status=&app_key=&page=1&page_size=20";

const INSTANCES = [
  {
    instance_id: "ai-1",
    app_key: "crm",
    template_key: "leave",
    biz_key: "REQ-1",
    status: "approved",
    originator_user_id: "emp-1",
    dingtalk_process_instance_id: "PROC-1",
    delivery_state: "delivered",
    delivery_attempts: 1,
    delivery_last_error: "",
    last_error: "",
    created_at: "2026-07-01T09:00:00Z",
    completed_at: "2026-07-01T10:00:00Z",
  },
  {
    instance_id: "ai-2",
    app_key: "erp",
    template_key: "purchase",
    biz_key: "REQ-2",
    status: "failed",
    originator_user_id: "emp-2",
    dingtalk_process_instance_id: "",
    delivery_state: "failed",
    delivery_attempts: 3,
    delivery_last_error: "HTTP 500",
    last_error: "callback error",
    created_at: "2026-07-02T09:00:00Z",
    completed_at: null,
  },
  {
    instance_id: "ai-3",
    app_key: "crm",
    template_key: "leave",
    biz_key: "REQ-3",
    status: "submitted",
    originator_user_id: "emp-3",
    dingtalk_process_instance_id: "PROC-3",
    delivery_state: "skipped",
    delivery_attempts: 0,
    delivery_last_error: "",
    last_error: "",
    created_at: "2026-07-03T09:00:00Z",
    completed_at: null,
  },
];

describe("ApprovalInstancesPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("按后端字段渲染审批实例列表: 状态与投递状态 badge、钉钉实例号和重投按钮", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      if (String(input) === LIST_URL) {
        return jsonResponse({
          data: INSTANCES,
          pagination: { page: 1, page_size: 20, total_items: 3, total_pages: 1 },
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByText("REQ-1")).toBeVisible();
    // 状态文案同时出现在过滤下拉里, badge 断言收敛到表格内。
    const table = within(screen.getByRole("table"));
    expect(table.getByText("PROC-1")).toBeVisible();
    expect(table.getByText("已通过")).toBeVisible();
    expect(table.getByText("已投递")).toBeVisible();
    expect(table.getByText("投递失败")).toBeVisible();
    expect(table.getByText("未配置推送")).toBeVisible();
    expect(table.getByText("审批中")).toBeVisible();
    expect(table.getByText("emp-2")).toBeVisible();
    // 仅投递失败的行出现重投按钮。
    expect(screen.getAllByRole("button", { name: "重新投递" })).toHaveLength(1);
    const failedRow = screen.getByText("REQ-2").closest("tr");
    expect(failedRow).not.toBeNull();
    expect(within(failedRow as HTMLTableRowElement).getByRole("button", { name: "重新投递" })).toBeVisible();
  });

  test("重投按实例防重复, 成功后立即按响应更新对应行并刷新列表", async () => {
    const anotherFailedInstance = {
      ...INSTANCES[1],
      instance_id: "ai-4",
      biz_key: "REQ-4",
    };
    const redeliverResponse = deferred<Response>();
    const refreshedList = deferred<Response>();
    let listRequestCount = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url === LIST_URL) {
        listRequestCount += 1;
        if (listRequestCount === 1) {
          return jsonResponse({
            data: [...INSTANCES, anotherFailedInstance],
            pagination: { page: 1, page_size: 20, total_items: 4, total_pages: 1 },
          });
        }
        return refreshedList.promise;
      }
      if (url === "/console/api/v1/operations/approval-instances/ai-2/redeliver" && init?.method === "POST") {
        return redeliverResponse.promise;
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderPage();

    const targetRow = (await screen.findByText("REQ-2")).closest("tr") as HTMLTableRowElement;
    const targetButton = within(targetRow).getByRole("button", { name: "重新投递" });

    await user.click(targetButton);

    await waitFor(() => {
      const currentTargetRow = screen.getByText("REQ-2").closest("tr") as HTMLTableRowElement;
      expect(within(currentTargetRow).getByRole("button", { name: "重新投递" })).toBeDisabled();
    });
    expect(
      within(screen.getByText("REQ-4").closest("tr") as HTMLTableRowElement).getByRole("button", { name: "重新投递" }),
    ).toBeEnabled();
    await user.click(
      within(screen.getByText("REQ-2").closest("tr") as HTMLTableRowElement).getByRole("button", { name: "重新投递" }),
    );

    await waitFor(() => {
      const redeliverCalls = fetchMock.mock.calls.filter(
        ([input]) => String(input) === "/console/api/v1/operations/approval-instances/ai-2/redeliver",
      );
      expect(redeliverCalls).toHaveLength(1);
    });

    redeliverResponse.resolve(
      jsonResponse({ approval_instance: { ...INSTANCES[1], delivery_state: "pending", delivery_last_error: "" } }),
    );

    expect(await screen.findByText("已重新投递")).toBeVisible();
    const updatedTargetRow = screen.getByText("REQ-2").closest("tr") as HTMLTableRowElement;
    const updatedOtherRow = screen.getByText("REQ-4").closest("tr") as HTMLTableRowElement;
    expect(within(updatedTargetRow).getByText("待投递")).toBeVisible();
    expect(within(updatedTargetRow).queryByRole("button", { name: "重新投递" })).not.toBeInTheDocument();
    expect(within(updatedOtherRow).getByRole("button", { name: "重新投递" })).toBeEnabled();

    // 刷新请求尚未返回时行状态已更新, 同时仍会触发后台刷新。
    await waitFor(() => {
      expect(listRequestCount).toBe(2);
    });
    refreshedList.resolve(
      jsonResponse({
        data: [{ ...INSTANCES[1], delivery_state: "pending", delivery_last_error: "" }],
        pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
      }),
    );
  });

  test("状态与 app_key 过滤会带参数重新请求", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.startsWith("/console/api/v1/operations/approval-instances?")) {
        return jsonResponse({
          data: [],
          pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 },
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderPage();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(LIST_URL, expect.anything()));

    await user.selectOptions(screen.getByLabelText("审批状态"), "approved");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/approval-instances?status=approved&app_key=&page=1&page_size=20",
        expect.anything(),
      );
    });

    await user.type(screen.getByLabelText("按发起应用 app_key 过滤"), "crm");
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/console/api/v1/operations/approval-instances?status=approved&app_key=crm&page=1&page_size=20",
        expect.anything(),
      );
    });
  });
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={["/console/operations/approval-instances"]}>
          <Routes>
            <Route path="/console/operations/approval-instances" element={<ApprovalInstancesPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}
