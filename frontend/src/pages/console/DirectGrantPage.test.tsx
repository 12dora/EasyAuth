import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { UserEvent } from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "../../components/antd/testing";
import { ToastProvider } from "../../components/ui/Toast";
import { DirectGrantPage } from "./DirectGrantPage";

// antd 多选下拉 + 权限选择表格在 jsdom 下与其余控制台用例同一档。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

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

const USER_OPTIONS = {
  data: [{ user_id: "u-1", name: "张三", department: "销售部", avatar_url: "" }],
};

describe("DirectGrantPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  test("未选被授权人时不能提交", async () => {
    stubFetch(async () => jsonResponse(CATALOG));

    renderPage();

    await screen.findByLabelText("应用");
    expect(screen.getByRole("button", { name: "授予权限" })).toBeDisabled();
  });

  test("选人、选应用与授权组、填说明后提交立即生效的授权", async () => {
    const fetchMock = stubFetch(async (url, init) => {
      if (url === "/console/api/v1/direct-grants") {
        expect(init?.method).toBe("POST");
        return jsonResponse(
          {
            data: {
              grant_id: 9,
              version: 1,
              user_id: "u-1",
              app_key: "crm",
              authorization_group_keys: ["sales"],
              direct_grants: [],
              grant_type: "permanent",
              grant_expires_at: null,
            },
          },
          201,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    const user = userEvent.setup({ delay: null });

    renderPage();
    await fillGrantForm(user);
    await user.click(screen.getByRole("button", { name: "授予权限" }));

    await waitFor(() => expect(directGrantBody(fetchMock)).not.toBeNull());
    expect(directGrantBody(fetchMock)).toEqual({
      user_id: "u-1",
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [],
      grant_type: "permanent",
      grant_expires_at: null,
      reason: "新同事接手客户维护",
    });
    // 被授权人保留, 目标草稿清空。
    expect(await screen.findByText("已选择：张三 · 销售部")).toBeVisible();
    await waitFor(() => expect(screen.getByLabelText("应用")).toHaveValue(""));
  });

  test("到期时间在填完之后走进过去, 点提交给出提示且不发请求", async () => {
    // 只伪造时钟, 不伪造定时器: 输入防抖与 react-query 仍走真实计时。
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
    const fetchMock = stubFetch(async (url) => {
      throw new Error(`Unexpected fetch: ${url}`);
    });
    const user = userEvent.setup({ delay: null });

    renderPage();
    await fillGrantForm(user);
    await user.selectOptions(screen.getByLabelText("有效期"), "timed");
    await user.type(screen.getByLabelText("到期时间"), datetimeLocalIn(60 * 60 * 1000));
    await waitFor(() => expect(screen.getByRole("button", { name: "授予权限" })).toBeEnabled());

    // 用户填完之后一直没点, 到期时间走进了过去; 按钮此刻仍然亮着(渲染时的结论已经过期)。
    vi.setSystemTime(new Date("2030-01-02T00:00:00Z"));
    await user.click(screen.getByRole("button", { name: "授予权限" }));

    expect(await screen.findByText("授权信息不完整")).toBeVisible();
    // 提示条逐条列出拦点; 到期时间字段自己也会亮红, 因此按列表项断言。
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toContain(
      "到期时间必须晚于当前时间。",
    );
    expect(fetchMock.mock.calls.some(([input]) => String(input) === "/console/api/v1/direct-grants")).toBe(false);
  });

  test("后端 422 的逐条语义错误全部展示", async () => {
    stubFetch(async (url) => {
      if (url === "/console/api/v1/direct-grants") {
        return jsonResponse(
          {
            error: {
              code: "SEMANTIC_VALIDATION_ERROR",
              message: "授权目标校验未通过",
              details: { errors: ["权限 crm.customer.read 不支持范围 GLOBAL", "授权组 sales 已停用"] },
            },
          },
          422,
        );
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });
    const user = userEvent.setup({ delay: null });

    renderPage();
    await fillGrantForm(user);
    await user.click(screen.getByRole("button", { name: "授予权限" }));

    expect(await screen.findByText("授权目标校验未通过")).toBeVisible();
    expect(screen.getByText("权限 crm.customer.read 不支持范围 GLOBAL")).toBeVisible();
    expect(screen.getByText("授权组 sales 已停用")).toBeVisible();
  });
});

async function fillGrantForm(user: UserEvent) {
  const grantee = await screen.findByLabelText("被授权人");
  await user.type(grantee, "张");
  await user.click(await screen.findByRole("option", { name: /张三/ }));

  await user.selectOptions(screen.getByLabelText("应用"), "crm");
  await user.click(await authorizationGroupOption(user, "销售"));
  await user.type(screen.getByLabelText("说明"), "新同事接手客户维护");

  await waitFor(() => expect(screen.getByRole("button", { name: "授予权限" })).toBeEnabled());
}

function directGrantBody(fetchMock: ReturnType<typeof stubFetch>): unknown {
  const call = fetchMock.mock.calls.find(([input]) => String(input) === "/console/api/v1/direct-grants");
  const body = call?.[1]?.body;
  return typeof body === "string" ? JSON.parse(body) : null;
}

function stubFetch(handler: (url: string, init?: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/console/api/v1/grant-catalog") {
      return jsonResponse(CATALOG);
    }
    if (url.startsWith("/console/api/v1/user-options?")) {
      return jsonResponse(USER_OPTIONS);
    }
    return handler(url, init);
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
      <MemoryRouter initialEntries={["/console/grants/direct"]}>
        <ToastProvider>
          <DirectGrantPage />
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** 「授权组」是 antd 多选下拉, 下拉是延迟挂载的 portal。 */
async function authorizationGroupOption(user: UserEvent, name: string): Promise<HTMLElement> {
  const combobox = screen.getByLabelText("授权组");
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

/** 以当前(可能被伪造的)时钟为基准, 生成 datetime-local 控件值。 */
function datetimeLocalIn(offsetMs: number): string {
  const target = new Date(Date.now() + offsetMs);
  return new Date(target.getTime() - target.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
