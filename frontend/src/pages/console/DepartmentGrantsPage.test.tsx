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

const SOURCE_SLUG = "dingtalk";
const CORP_ID = "corp-1";

/** 部门名; 根部门的名字可被用例改写(钉钉企业根部门在镜像里没有名字)。 */
type DepartmentNames = Record<string, string>;
const DEFAULT_NAMES: DepartmentNames = { "1": "公司", "12": "销售部", "13": "技术部" };

function treePayload(names: DepartmentNames) {
  return {
    data: {
      source_slug: SOURCE_SLUG,
      corp_id: CORP_ID,
      synced_at: "2026-09-01T02:00:00Z",
      root: {
        dept_id: "1",
        name: names["1"],
        member_count: 5,
        children: [
          { dept_id: "12", name: names["12"], member_count: 8, children: [] },
          { dept_id: "13", name: names["13"], member_count: 6, children: [] },
        ],
      },
    },
  };
}

/** 部门摘要与「祖先或自身」链(自根到自身), 后端按这条链算继承。 */
const DEPARTMENTS: Record<string, { memberCount: number; subtreeMemberCount: number; chain: string[] }> = {
  "1": { memberCount: 5, subtreeMemberCount: 21, chain: ["1"] },
  "12": { memberCount: 8, subtreeMemberCount: 8, chain: ["1", "12"] },
  "13": { memberCount: 6, subtreeMemberCount: 6, chain: ["1", "13"] },
};

const APPS: Record<string, { app_key: string; name: string; alias: string }> = {
  crm: { app_key: "crm", name: "CRM", alias: "客户管理" },
};

const GROUPS: Record<string, { key: string; name: string; kind: string }> = {
  sales: { key: "sales", name: "销售", kind: "role" },
};

const PERMISSIONS: Record<string, { key: string; name: string; scope: string; scope_name: string }> = {
  "crm.customer.read:SELF": { key: "crm.customer.read", name: "查看客户", scope: "SELF", scope_name: "本人" },
  "crm.order.read:DEPT": { key: "crm.order.read", name: "查看订单", scope: "DEPT", scope_name: "本部门" },
  "crm.order.write:DEPT": { key: "crm.order.write", name: "编辑订单", scope: "DEPT", scope_name: "本部门" },
  "crm.report.view:DEPT": { key: "crm.report.view", name: "查看报表", scope: "DEPT", scope_name: "本部门" },
  "crm.contract.sign:DEPT": { key: "crm.contract.sign", name: "签署合同", scope: "DEPT", scope_name: "本部门" },
  "crm.customer.export:DEPT": { key: "crm.customer.export", name: "导出客户", scope: "DEPT", scope_name: "本部门" },
};

const CATALOG = {
  apps: [{ id: 1, ...APPS.crm }],
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
      permissions: Object.values(PERMISSIONS).map((permission, index) => ({
        id: 100 + index,
        app_key: "crm",
        key: permission.key,
        name: permission.name,
        scopes: [{ key: permission.scope, name: permission.scope_name }],
      })),
    },
  ],
  ungrouped_permissions: [],
};

interface PolicyBody {
  app_key: string;
  authorization_group_keys: string[];
  direct_grants: { permission: string; scope: string }[];
  grant_type: "permanent" | "timed";
  grant_expires_at: string | null;
  reason: string;
}

interface StoredPolicy {
  id: number;
  definedOn: string;
  body: PolicyBody;
}

/**
 * 后端的最小可信替身: 策略按定义所在部门存一份, 读取时按「祖先或自身」链展开成继承行。
 * 写操作真的改这份存量, 否则「删掉后行还在」「祖先改了下游继承行没变」这类回归会被静默放过。
 */
function createPolicyStore() {
  let nextId = 100;
  const policies: StoredPolicy[] = [
    {
      id: 3,
      definedOn: "1",
      body: {
        app_key: "crm",
        authorization_group_keys: ["sales"],
        direct_grants: [{ permission: "crm.order.read", scope: "DEPT" }],
        grant_type: "permanent",
        grant_expires_at: null,
        reason: "全员可查看本人客户",
      },
    },
    {
      id: 7,
      definedOn: "12",
      body: {
        app_key: "crm",
        authorization_group_keys: [],
        direct_grants: [
          { permission: "crm.order.write", scope: "DEPT" },
          { permission: "crm.report.view", scope: "DEPT" },
          { permission: "crm.contract.sign", scope: "DEPT" },
          { permission: "crm.customer.export", scope: "DEPT" },
          { permission: "crm.order.read", scope: "DEPT" },
        ],
        grant_type: "timed",
        grant_expires_at: "2026-12-31T15:59:59Z",
        reason: "销售部季度支持",
      },
    },
  ];

  return {
    listFor(deptId: string, names: DepartmentNames) {
      const department = DEPARTMENTS[deptId];
      // 本部门在前, 再由近及远地列出继承来的策略。
      const order = [...department.chain].reverse();
      return order.flatMap((ownerDeptId) =>
        policies
          .filter((policy) => policy.definedOn === ownerDeptId)
          .map((policy) => serializePolicy(policy, deptId, names)),
      );
    },
    create(deptId: string, body: PolicyBody, names: DepartmentNames) {
      nextId += 1;
      const policy: StoredPolicy = { id: nextId, definedOn: deptId, body };
      policies.push(policy);
      return serializePolicy(policy, deptId, names);
    },
    update(id: number, body: PolicyBody, names: DepartmentNames) {
      const policy = policies.find((item) => item.id === id);
      if (!policy) {
        throw new Error(`策略 ${id} 不存在`);
      }
      policy.body = body;
      return serializePolicy(policy, policy.definedOn, names);
    },
    remove(id: number) {
      const index = policies.findIndex((item) => item.id === id);
      if (index === -1) {
        throw new Error(`策略 ${id} 不存在`);
      }
      policies.splice(index, 1);
    },
  };
}

function serializePolicy(policy: StoredPolicy, deptId: string, names: DepartmentNames) {
  const owner = DEPARTMENTS[policy.definedOn];
  return {
    id: policy.id,
    app: APPS[policy.body.app_key],
    authorization_groups: policy.body.authorization_group_keys.map((key) => GROUPS[key]),
    permissions: policy.body.direct_grants.map((grant) => PERMISSIONS[`${grant.permission}:${grant.scope}`]),
    grant_type: policy.body.grant_type,
    expires_at: policy.body.grant_expires_at,
    reason: policy.body.reason,
    defined_on: { dept_id: policy.definedOn, name: names[policy.definedOn] },
    inherited: policy.definedOn !== deptId,
    affected_user_count: owner.subtreeMemberCount,
    created_at: "2026-08-01T02:00:00Z",
    updated_at: "2026-08-01T02:00:00Z",
    created_by: { user_id: "admin-1", name: "管理员" },
    updated_by: { user_id: "admin-1", name: "管理员" },
  };
}

function departmentPayload(deptId: string, store: ReturnType<typeof createPolicyStore>, names: DepartmentNames) {
  const department = DEPARTMENTS[deptId];
  return {
    data: {
      department: {
        dept_id: deptId,
        name: names[deptId],
        path: department.chain.map((id) => ({ dept_id: id, name: names[id] })),
        member_count: department.memberCount,
        subtree_member_count: department.subtreeMemberCount,
      },
      items: store.listFor(deptId, names),
    },
  };
}

describe("DepartmentGrantsPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("默认选中根部门, 按目录来源与企业 ID 取该部门的授权", async () => {
    const { fetchMock } = stubFetch();

    renderPage();

    expect(await screen.findByRole("treeitem", { name: /公司/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("直属 5 人 · 含子部门 21 人")).toBeVisible();
    expect(await screen.findByText("客户管理 (CRM)")).toBeVisible();
    expect(screen.getByText("本部门")).toBeVisible();
    expect(screen.getByText("永久")).toBeVisible();

    const url = policiesRequestUrl(fetchMock, "1");
    expect(url).not.toBeNull();
    const query = new URLSearchParams(String(url).split("?")[1]);
    expect(query.get("source_slug")).toBe(SOURCE_SLUG);
    expect(query.get("corp_id")).toBe(CORP_ID);
  });

  test("选中子部门后按该部门取授权, 继承行标出来源部门", async () => {
    const { fetchMock } = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByText("销售部"));

    expect(await screen.findByText("继承自 公司")).toBeVisible();
    expect(screen.getByText("销售部季度支持")).toBeVisible();
    expect(policiesRequestUrl(fetchMock, "12")).not.toBeNull();
  });

  test("授权内容超出平铺上限时, 键盘聚焦 +N 即可看到其余项", async () => {
    stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByText("销售部"));

    // 销售部本部门策略有 5 项权限: 平铺 3 项, 其余进 +2。
    const moreButton = await screen.findByRole("button", { name: "查看其余 2 项授权内容" });
    expect(moreButton).toHaveTextContent("+2");

    moreButton.focus();

    // 折叠掉的两项(导出客户 / 查看订单)只在浮层里, 聚焦即可读到。
    // 浮层的进场动画在 jsdom 里跑不完(rc-motion 依赖真实的 transition 事件), 因此断言内容已挂到浮层里。
    const tooltip = await screen.findByRole("tooltip");
    expect(within(tooltip).getByText("导出客户 · 本部门")).toBeInTheDocument();
    expect(within(tooltip).getByText("查看订单 · 本部门")).toBeInTheDocument();
  });

  test("在公司新增授权后, 子部门出现对应的继承行", async () => {
    const { fetchMock } = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByRole("button", { name: "新增授权" }));

    const dialog = await screen.findByRole("dialog", { name: "新增授权" });
    expect(within(dialog).getByText("将自动授予 公司 及其子部门的全部在职人员")).toBeVisible();
    await fillGrantForm(user, dialog, "公司统一放开销售权限");
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(createPolicyBody(fetchMock)).not.toBeNull());
    expect(createPolicyBody(fetchMock)).toEqual({
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [],
      grant_type: "permanent",
      grant_expires_at: null,
      reason: "公司统一放开销售权限",
      source_slug: SOURCE_SLUG,
      corp_id: CORP_ID,
    });
    expect(await screen.findByText("已新增授权")).toBeVisible();
    expect(await screen.findByText("公司统一放开销售权限")).toBeVisible();

    await user.click(screen.getByText("销售部"));
    // 新策略定义在公司, 因此在销售部是继承行。
    await waitFor(() => expect(screen.getByText("公司统一放开销售权限")).toBeVisible());
    expect(screen.getAllByText("继承自 公司")).toHaveLength(2);
  });

  test("在子部门编辑继承行改的是定义它的那条策略, 公司与其它部门同步更新", async () => {
    const { fetchMock } = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");
    await user.click(screen.getByText("销售部"));
    await screen.findByText("继承自 公司");

    // 继承行的编辑入口改的是「公司」上的那条策略。
    await user.click(within(rowByText("全员可查看本人客户")).getByRole("button", { name: "编辑" }));
    const dialog = await screen.findByRole("dialog", { name: "编辑 公司 的授权" });
    expect(within(dialog).getByText("将自动授予 公司 及其子部门的全部在职人员")).toBeVisible();
    // 编辑态锁定应用: 后端拒绝跨应用改写。
    const appSelect = within(dialog).getByLabelText("应用");
    expect(appSelect).toBeDisabled();
    expect(appSelect).toHaveValue("crm");

    const reason = within(dialog).getByLabelText("说明");
    await user.clear(reason);
    await user.type(reason, "公司层面收敛为只读");
    await user.click(within(dialog).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(updatePolicyBody(fetchMock, 3)).not.toBeNull());
    expect(updatePolicyBody(fetchMock, 3)).toEqual({
      app_key: "crm",
      authorization_group_keys: ["sales"],
      direct_grants: [{ permission: "crm.order.read", scope: "DEPT" }],
      grant_type: "permanent",
      grant_expires_at: null,
      reason: "公司层面收敛为只读",
    });
    expect(await screen.findByText("已更新授权")).toBeVisible();
    await waitFor(() => expect(screen.getByText("公司层面收敛为只读")).toBeVisible());

    await user.click(screen.getByText("公司"));
    await waitFor(() => expect(screen.getByText("公司层面收敛为只读")).toBeVisible());
    expect(screen.queryByText("全员可查看本人客户")).not.toBeInTheDocument();
  });

  test("删除公司的策略后, 已浏览过的子部门里的继承行也随之消失", async () => {
    const { fetchMock } = stubFetch();
    const user = userEvent.setup({ delay: null });

    renderPage();
    await screen.findByText("客户管理 (CRM)");

    // 先把两个子部门读进缓存, 删除后必须失效重取, 不能拿旧缓存继续渲染继承行。
    await user.click(screen.getByText("销售部"));
    await screen.findByText("继承自 公司");
    await user.click(screen.getByText("技术部"));
    await screen.findByText("继承自 公司");
    await user.click(screen.getByText("公司"));
    await screen.findByText("本部门");

    await user.click(within(rowByText("全员可查看本人客户")).getByRole("button", { name: "删除" }));
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
    await waitFor(() => expect(screen.queryByText("全员可查看本人客户")).not.toBeInTheDocument());
    expect(await screen.findByText("该部门暂无授权")).toBeVisible();

    await user.click(screen.getByText("技术部"));
    await waitFor(() => expect(screen.getByText("该部门暂无授权")).toBeVisible());

    await user.click(screen.getByText("销售部"));
    await waitFor(() => expect(screen.getByText("销售部季度支持")).toBeVisible());
    expect(screen.queryByText("继承自 公司")).not.toBeInTheDocument();
  });

  test("根部门没有名字时按「全公司」展示, 且可选中并列出授权", async () => {
    stubFetch({ rootName: "" });
    const user = userEvent.setup({ delay: null });

    renderPage();

    const root = await screen.findByRole("treeitem", { name: /全公司/ });
    expect(root).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("客户管理 (CRM)")).toBeVisible();
    expect(screen.getByRole("button", { name: "新增授权" })).toBeEnabled();

    await user.click(screen.getByText("销售部"));
    // 定义在根部门上的策略, 在子部门里同样按「全公司」展示来源。
    expect(await screen.findByText("继承自 全公司")).toBeVisible();

    await user.click(screen.getByText("全公司"));
    await waitFor(() => expect(screen.getByText("本部门")).toBeVisible());
    expect(screen.getByText("直属 5 人 · 含子部门 21 人")).toBeVisible();
  });

  test("部门树契约不符时立刻显示错误页, 不会一直停在加载中", async () => {
    stubFetch({
      // member_count 缺失: 契约错误不是瞬时故障, 不该被重试成"一直在加载"。
      tree: () =>
        jsonResponse({
          data: {
            source_slug: SOURCE_SLUG,
            corp_id: CORP_ID,
            synced_at: "2026-09-01T02:00:00Z",
            root: { dept_id: "1", name: "", children: [] },
          },
        }),
    });

    renderPage();

    expect(await screen.findByText("组织架构加载失败")).toBeVisible();
    expect(screen.getByText("部门树.data.root.member_count 必须为数字")).toBeVisible();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeVisible();
    expect(screen.queryByText("正在加载组织架构")).not.toBeInTheDocument();
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

async function fillGrantForm(user: UserEvent, dialog: HTMLElement, reason: string) {
  await user.selectOptions(within(dialog).getByLabelText("应用"), "crm");
  await user.click(await authorizationGroupOption(user, dialog, "销售"));
  await user.type(within(dialog).getByLabelText("说明"), reason);

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

function rowByText(text: string): HTMLElement {
  const cell = screen.getByText(text);
  const row = cell.closest("tr");
  if (!(row instanceof HTMLElement)) {
    throw new Error(`「${text}」不在表格行里`);
  }
  return row;
}

type FetchMock = ReturnType<typeof vi.fn<typeof fetch>>;

function policiesRequestUrl(fetchMock: FetchMock, deptId: string): string | null {
  const call = fetchMock.mock.calls.find(([input]) =>
    String(input).startsWith(`/console/api/v1/departments/${deptId}/grant-policies?`),
  );
  return call ? String(call[0]) : null;
}

function createPolicyBody(fetchMock: FetchMock): unknown {
  const call = fetchMock.mock.calls.find(
    ([input, init]) => String(input) === "/console/api/v1/departments/1/grant-policies" && init?.method === "POST",
  );
  const body = call?.[1]?.body;
  return typeof body === "string" ? JSON.parse(body) : null;
}

function updatePolicyBody(fetchMock: FetchMock, policyId: number): unknown {
  const call = fetchMock.mock.calls.find(
    ([input, init]) =>
      String(input) === `/console/api/v1/department-grant-policies/${policyId}` && init?.method === "PUT",
  );
  const body = call?.[1]?.body;
  return typeof body === "string" ? JSON.parse(body) : null;
}

function stubFetch({ tree, rootName = DEFAULT_NAMES["1"] }: { tree?: () => Response; rootName?: string } = {}) {
  const store = createPolicyStore();
  const names: DepartmentNames = { ...DEFAULT_NAMES, "1": rootName };
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const url = String(input);
    const [path, search = ""] = url.split("?");
    const body = typeof init?.body === "string" ? (JSON.parse(init.body) as PolicyBody & Record<string, unknown>) : null;

    if (path === "/console/api/v1/departments/tree") {
      return tree ? tree() : jsonResponse(treePayload(names));
    }
    if (path === "/console/api/v1/grant-catalog") {
      return jsonResponse(CATALOG);
    }

    const listMatch = /^\/console\/api\/v1\/departments\/([^/]+)\/grant-policies$/.exec(path);
    if (listMatch && (init?.method ?? "GET") === "GET") {
      const deptId = decodeURIComponent(listMatch[1]);
      const query = new URLSearchParams(search);
      if (query.get("source_slug") !== SOURCE_SLUG || query.get("corp_id") !== CORP_ID) {
        return jsonResponse({ error: { code: "BAD_REQUEST", message: "缺少目录来源参数" } }, 400);
      }
      return jsonResponse(departmentPayload(deptId, store, names));
    }
    if (listMatch && init?.method === "POST" && body) {
      const { source_slug: sourceSlug, corp_id: corpId, ...policyBody } = body;
      if (sourceSlug !== SOURCE_SLUG || corpId !== CORP_ID) {
        return jsonResponse({ error: { code: "BAD_REQUEST", message: "缺少目录来源参数" } }, 400);
      }
      return jsonResponse({ data: store.create(decodeURIComponent(listMatch[1]), policyBody as PolicyBody, names) }, 201);
    }

    const policyMatch = /^\/console\/api\/v1\/department-grant-policies\/(\d+)$/.exec(path);
    if (policyMatch && init?.method === "PUT" && body) {
      return jsonResponse({ data: store.update(Number(policyMatch[1]), body, names) });
    }
    if (policyMatch && init?.method === "DELETE") {
      store.remove(Number(policyMatch[1]));
      return new Response(null, { status: 204 });
    }

    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, store };
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
