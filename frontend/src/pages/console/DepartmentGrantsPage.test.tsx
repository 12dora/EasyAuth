import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserEvent } from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../../components/antd/testing";
import { ToastProvider } from "../../components/ui/Toast";
import { DepartmentGrantsPage } from "./DepartmentGrantsPage";

// antd 表格 + 弹窗里的权限选择器在 jsdom 下与其余控制台用例同一档。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const TREE = {
  data: {
    source_slug: "dingtalk",
    corp_id: "corp-1",
    synced_at: "2026-09-01T02:00:00Z",
    root: {
      dept_id: "1",
      name: "公司",
      member_count: 5,
      children: [
        { dept_id: "12", name: "销售部", member_count: 8, children: [] },
        { dept_id: "13", name: "技术部", member_count: 6, children: [] },
      ],
    },
  },
};

const CATALOG = {
  apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "客户管理" }],
  approver_options: [],
  authorization_groups: [
    {
      id: 11,
      app_key: "crm",
      key: "sales",
      kind: "role",
      name: "销售",
      grants: [{ permission_key: "crm.customer.read", scope_key: "SELF" }],
    },
  ],
  permission_groups: [
    {
      id: 1,
      app_key: "crm",
      type: "group",
      key: "crm.customer",
      name: "客户管理",
      permissions: [
        {
          id: 101,
          app_key: "crm",
          key: "crm.customer.read",
          name: "查看客户",
          scopes: [{ key: "SELF", name: "本人" }],
        },
      ],
    },
  ],
  ungrouped_permissions: [],
};

const COMPANY_POLICY = {
  id: 3,
  app: { app_key: "crm", name: "CRM", alias: "客户管理" },
  authorization_groups: [{ key: "sales", name: "销售", kind: "role" }],
  permissions: [{ key: "crm.customer.read", name: "查看客户", scope: "SELF", scope_name: "本人" }],
  grant_type: "permanent",
  expires_at: null,
  reason: "全员可查看本人客户",
  defined_on: { dept_id: "1", name: "公司" },
  inherited: false,
  affected_user_count: 21,
  created_at: "2026-08-01T02:00:00Z",
  updated_at: "2026-08-01T02:00:00Z",
  created_by: { user_id: "admin-1", name: "管理员" },
  updated_by: { user_id: "admin-1", name: "管理员" },
};

const COMPANY_POLICIES = {
  data: {
    department: {
      dept_id: "1",
      name: "公司",
      path: [{ dept_id: "1", name: "公司" }],
      member_count: 5,
      subtree_member_count: 21,
    },
    items: [COMPANY_POLICY],
  },
};

const SALES_POLICIES = {
  data: {
    department: {
      dept_id: "12",
      name: "销售部",
      path: [
        { dept_id: "1", name: "公司" },
        { dept_id: "12", name: "销售部" },
      ],
      member_count: 8,
      subtree_member_count: 8,
    },
    items: [
      { ...COMPANY_POLICY, inherited: true },
      {
        ...COMPANY_POLICY,
        id: 7,
        authorization_groups: [],
        permissions: [{ key: "crm.order.write", name: "编辑订单", scope: "DEPT", scope_name: "本部门" }],
        grant_type: "timed",
        expires_at: "2026-12-31T15:59:59Z",
        reason: "销售部季度支持",
        defined_on: { dept_id: "12", name: "销售部" },
        inherited: false,
        affected_user_count: 8,
      },
    ],
  },
};

describe("DepartmentGrantsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("默认选中根部门并展示它的授权", async () => {
    stubFetch();

    renderPage();

    expect(await screen.findByRole("treeitem", { name: /公司/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("直属 5 人 · 含子部门 21 人")).toBeVisible();
    expect(await screen.findByText("客户管理 (CRM)")).toBeVisible();
    expect(screen.getByText("本部门")).toBeVisible();
    expect(screen.getByText("永久")).toBeVisible();
  });

  test("选中子部门后按该部门取授权, 继承行标出来源部门", async () => {
    const fetchMock = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByText("销售部"));

    expect(await screen.findByText("继承自 公司")).toBeVisible();
    expect(screen.getByText("销售部季度支持")).toBeVisible();
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).startsWith("/console/api/v1/departments/12/grant-policies?"),
      ),
    ).toBe(true);
  });

  test("新增授权提交到当前部门, 载荷带上目录来源与企业 ID", async () => {
    const fetchMock = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByRole("button", { name: "新增授权" }));

    const dialog = await screen.findByRole("dialog", { name: "新增授权" });
    expect(within(dialog).getByText("将自动授予 公司 及其子部门的全部在职人员")).toBeVisible();
    await fillGrantForm(user, dialog);
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(createPolicyBody(fetchMock)).not.toBeNull());
    expect(createPolicyBody(fetchMock)).toEqual({
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [],
      grant_type: "permanent",
      grant_expires_at: null,
      reason: "部门统一授权",
      source_slug: "dingtalk",
      corp_id: "corp-1",
    });
    expect(await screen.findByText("已新增授权")).toBeVisible();
  });

  test("删除二次确认后调用删除接口", async () => {
    const fetchMock = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByRole("button", { name: "删除" }));

    const dialog = await screen.findByRole("dialog", { name: "删除授权" });
    await user.click(within(dialog).getByRole("button", { name: "删除" }));

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input) === "/console/api/v1/department-grant-policies/3" && init?.method === "DELETE",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("已删除授权")).toBeVisible();
  });

  test("尚未同步钉钉组织架构时给出同步指引", async () => {
    stubFetch({
      tree: () =>
        jsonResponse(
          {
            error: {
              code: "CONFLICT",
              message: "尚未同步钉钉组织架构",
              details: { reason: "directory_not_synced" },
            },
          },
          409,
        ),
    });

    renderPage();

    expect(await screen.findByText("尚未同步钉钉组织架构")).toBeVisible();
    expect(screen.getByRole("button", { name: "新增授权" })).toBeDisabled();
    expect(screen.queryByRole("tree")).not.toBeInTheDocument();
  });
});

async function fillGrantForm(user: UserEvent, dialog: HTMLElement) {
  await user.selectOptions(within(dialog).getByLabelText("应用"), "crm");
  await user.click(await authorizationGroupOption(user, dialog, "销售"));
  await user.type(within(dialog).getByLabelText("说明"), "部门统一授权");

  await waitFor(() => expect(within(dialog).getByRole("button", { name: "保存" })).toBeEnabled());
}

/** 「授权组」是 antd 多选下拉, 下拉是延迟挂载的 portal(挂在 body 上, 不在弹窗节点里)。 */
async function authorizationGroupOption(user: UserEvent, dialog: HTMLElement, name: string): Promise<HTMLElement> {
  const combobox = within(dialog).getByLabelText("授权组");
  const listId = combobox.getAttribute("aria-controls") ?? "";
  const selector = combobox.closest(".ant-select")?.querySelector(".ant-select-selector");
  if (!(selector instanceof HTMLElement)) {
    throw new Error("「授权组」不是 antd Select");
  }
  await user.click(selector);
  const dropdown = await waitFor(() => {
    const node = document.getElementById(listId)?.closest(".ant-select-dropdown");
    if (!(node instanceof HTMLElement)) {
      throw new Error("「授权组」的下拉没有出现");
    }
    return node;
  });
  return within(dropdown).getByTitle(name);
}

function createPolicyBody(fetchMock: ReturnType<typeof stubFetch>): unknown {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input) === "/console/api/v1/departments/1/grant-policies" && init?.method === "POST",
  );
  const body = call?.[1]?.body;
  return typeof body === "string" ? JSON.parse(body) : null;
}

function stubFetch({ tree }: { tree?: () => Response } = {}) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/console/api/v1/departments/tree") {
      return tree ? tree() : jsonResponse(TREE);
    }
    if (url === "/console/api/v1/grant-catalog") {
      return jsonResponse(CATALOG);
    }
    if (url.startsWith("/console/api/v1/departments/1/grant-policies?")) {
      return jsonResponse(COMPANY_POLICIES);
    }
    if (url.startsWith("/console/api/v1/departments/12/grant-policies?")) {
      return jsonResponse(SALES_POLICIES);
    }
    if (url === "/console/api/v1/departments/1/grant-policies" && init?.method === "POST") {
      return jsonResponse({ data: COMPANY_POLICY }, 201);
    }
    if (url === "/console/api/v1/department-grant-policies/3" && init?.method === "PUT") {
      return jsonResponse({ data: COMPANY_POLICY });
    }
    if (url === "/console/api/v1/department-grant-policies/3" && init?.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  renderWithAntd(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/console/grants/departments"]}>
        <ToastProvider>
          <DepartmentGrantsPage />
        </ToastProvider>
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
