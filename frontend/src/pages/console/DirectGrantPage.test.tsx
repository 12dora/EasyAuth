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
        {
          id: 102,
          app_key: "crm",
          key: "crm.customer.export",
          name: "导出客户",
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

const NO_CURRENT_GRANT = { grant: null };
/** 交给用例自己的 handler 处理「当前授权」请求(用来构造读取失败)。 */
const CURRENT_GRANT_FROM_HANDLER = Symbol("current-grant-from-handler");

/** 张三在 CRM 上的现有授权: 本人来源的销售组 + 限时直接权限, 另有组织授权下发的审计组与报表权限。 */
const CURRENT_GRANT = {
  grant: {
    id: 6,
    version: 3,
    is_current: true,
    status: "active",
    user_id: "u-1",
    user_name: "张三",
    app_key: "crm",
    app_name: "CRM",
    app_alias: "客户管理",
    grant_type: "mixed",
    grant_expires_at: "2030-06-30T15:59:59.123456+00:00",
    authorization_groups: [
      { key: "sales", kind: "role", name: "销售", expires_at: null, source: "user" },
      { key: "audit", kind: "role", name: "审计", expires_at: null, source: "department" },
    ],
    direct_grants: [
      {
        permission: "crm.customer.export",
        permission_name: "导出客户",
        scope: "SELF",
        scope_name: "本人",
        expires_at: "2030-06-30T15:59:59.123456+00:00",
        source: "user",
      },
      {
        permission: "crm.report.view",
        permission_name: "查看报表",
        scope: "ALL",
        scope_name: "全部",
        expires_at: null,
        source: "department",
      },
    ],
    groups: [
      { key: "sales", kind: "role", name: "销售" },
      { key: "audit", kind: "role", name: "审计" },
    ],
    grants: [],
  },
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
    // 成功提示用姓名而不是用户 ID。
    expect(await screen.findByText("已授予 张三 客户管理 (CRM) 的权限")).toBeVisible();
    // 被授权人保留(输入框显示姓名, 部门与 ID 在次要行), 目标草稿清空。
    expect(screen.getByLabelText("被授权人")).toHaveValue("张三");
    expect(screen.getByText("销售部")).toBeVisible();
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

  test("选定被授权人与应用后回填现有权限, 组织授权来源只读", async () => {
    const fetchMock = stubFetch(async (url) => {
      if (url === "/console/api/v1/direct-grants") {
        return jsonResponse({ data: { grant_id: 9 } }, 201);
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }, CURRENT_GRANT);
    const user = userEvent.setup({ delay: null });

    renderPage();
    await selectGrantee(user);
    await user.selectOptions(screen.getByLabelText("应用"), "crm");

    // 本人来源的授权组与直接权限回填进表单, 管理员在现状上做加减。
    await waitFor(() => expect(screen.getByLabelText("有效期")).toHaveValue("timed"));
    expect(await selectedAuthorizationGroupNames(user)).toEqual(["销售"]);
    await user.click(await screen.findByRole("button", { name: "展开 客户管理" }));
    expect(screen.getByRole("checkbox", { name: "选择 crm.customer.export 本人" })).toBeChecked();
    // 期限取本人来源成员关系里最早的到期时间。
    expect(screen.getByLabelText("到期时间")).toHaveValue(
      localDatetimeValue("2030-06-30T15:59:59.123456+00:00"),
    );

    // 组织授权下发的部分只读展示, 不进草稿。
    const departmentBlock = screen.getByRole("heading", { name: "来自组织授权" }).closest("section");
    expect(within(departmentBlock as HTMLElement).getByText("审计")).toBeVisible();
    expect(within(departmentBlock as HTMLElement).getByText("查看报表 · 全部")).toBeVisible();

    // 提交时只替换本人来源的成员关系, 秒与微秒都不丢。
    await user.type(screen.getByLabelText("说明"), "延续现有权限");
    await user.click(screen.getByRole("button", { name: "授予权限" }));

    await waitFor(() => expect(directGrantBody(fetchMock)).not.toBeNull());
    expect(directGrantBody(fetchMock)).toEqual({
      user_id: "u-1",
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [{ permission: "crm.customer.export", scope: "SELF" }],
      grant_type: "timed",
      grant_expires_at: "2030-06-30T15:59:59.123456+00:00",
      reason: "延续现有权限",
    });
  });

  test("现有权限读取失败时给出提示, 表单停在空白态", async () => {
    stubFetch(
      async (url) => {
        if (url.endsWith("/current-grant")) {
          return jsonResponse(
            { error: { code: "INTERNAL_ERROR", message: "目录服务暂时不可用" } },
            500,
          );
        }
        throw new Error(`Unexpected fetch: ${url}`);
      },
      CURRENT_GRANT_FROM_HANDLER,
    );
    const user = userEvent.setup({ delay: null });

    renderPage();
    await selectGrantee(user);
    await user.selectOptions(screen.getByLabelText("应用"), "crm");

    expect(await screen.findByText("现有权限读取失败")).toBeVisible();
    expect(await selectedAuthorizationGroupNames(user)).toEqual([]);
    expect(screen.queryByRole("heading", { name: "来自组织授权" })).toBeNull();
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

async function selectGrantee(user: UserEvent) {
  const grantee = await screen.findByLabelText("被授权人");
  await user.type(grantee, "张");
  await user.click(await screen.findByRole("option", { name: /张三/ }));
}

async function fillGrantForm(user: UserEvent) {
  await selectGrantee(user);

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

function stubFetch(
  handler: (url: string, init?: RequestInit) => Promise<Response>,
  currentGrant: unknown = NO_CURRENT_GRANT,
) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    if (url === "/console/api/v1/grant-catalog") {
      return jsonResponse(CATALOG);
    }
    if (url.startsWith("/console/api/v1/user-options?")) {
      return jsonResponse(USER_OPTIONS);
    }
    if (url.endsWith("/current-grant") && currentGrant !== CURRENT_GRANT_FROM_HANDLER) {
      return jsonResponse(currentGrant);
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

/** 已选授权组: 只读计数在只读态下不可见, 选中态从下拉面板里读(与门户用例同一口径)。 */
async function selectedAuthorizationGroupNames(user: UserEvent): Promise<string[]> {
  const combobox = screen.getByLabelText("授权组");
  const listId = combobox.getAttribute("aria-controls") ?? "";
  const mounted = document.getElementById(listId)?.closest(".ant-select-dropdown");
  const dropdown =
    mounted instanceof HTMLElement ? mounted : (await authorizationGroupOption(user, "销售")).closest(".ant-select-dropdown");
  return [...(dropdown as HTMLElement).querySelectorAll(".ant-select-item-option[aria-selected='true']")].map(
    (option) => option.getAttribute("title") ?? "",
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

/** 后端 ISO 时间戳在 datetime-local 控件里的分钟精度投影(本地时区)。 */
function localDatetimeValue(iso: string): string {
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
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
