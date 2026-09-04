import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { directGrantSelectionKey } from "./accessRequestSelection";
import { ACCESS_REQUEST_MAX_APPROVERS, ACCESS_REQUEST_MAX_REASON_LENGTH } from "./accessRequestTypes";
import { useAccessRequestForm } from "./useAccessRequestForm";

function catalogResponse() {
  return jsonResponse(
    {
      apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["me", "boss"] }],
      approver_options: [
        { user_id: "me", name: "我" },
        { user_id: "boss", name: "老板" },
      ],
      authorization_groups: [
        { id: 11, app_key: "crm", key: "reader", kind: "role", name: "只读", requestable: true, requires_approval: true },
      ],
      permission_groups: [],
      // app_key 缺省 => 应用无关的未分组权限, FF-12 应在选定应用后仍然可见。
      ungrouped_permissions: [{ id: 101, key: "shared.view", name: "共享查看", scopes: [{ key: "GLOBAL", name: "全局" }] }],
    },
  );
}

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function scopedCatalog(overrides: Record<string, unknown> = {}) {
  return {
    apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: ["boss"] }],
    approver_options: [{ user_id: "boss", name: "老板" }],
    authorization_groups: [],
    permission_groups: [],
    ungrouped_permissions: [
      {
        id: 101,
        app_key: "crm",
        key: "customer.read",
        name: "查看客户",
        scopes: [
          { key: "SELF", name: "本人" },
          { key: "MANAGED_USERS", name: "下级用户" },
        ],
      },
    ],
    ...overrides,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return createElement(QueryClientProvider, { client }, children);
}

async function renderReadyForm(currentUserId = "") {
  const view = renderHook(() => useAccessRequestForm(currentUserId), { wrapper });
  await waitFor(() => expect(view.result.current.apps).toHaveLength(1));
  return view;
}

describe("useAccessRequestForm", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("FF-7: 申请人被排除出审批人候选与默认审批人", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => catalogResponse()));
    const { result } = await renderReadyForm("me");

    expect(result.current.approverOptions.map((option) => option.user_id)).toEqual(["boss"]);

    act(() => result.current.changeAppKey("crm"));
    await waitFor(() => expect(result.current.selectedApproverUserIds).toEqual(["boss"]));
  });

  test("FF-12: 选定应用后应用无关的未分组权限仍然可见", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => catalogResponse()));
    const { result } = await renderReadyForm("");

    act(() => result.current.changeAppKey("crm"));
    await waitFor(() =>
      expect(result.current.ungroupedPermissions.map((permission) => permission.key)).toContain("shared.view"),
    );
  });

  test("FF-14: 纯空白理由不能提交且提交理由会被 trim", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => catalogResponse()));
    const { result } = await renderReadyForm("");

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["reader"]));
    await waitFor(() => expect(result.current.selectedApproverUserIds.length).toBeGreaterThan(0));

    act(() => result.current.changeReason("   \n  "));
    expect(result.current.canSubmit).toBe(false);

    act(() => result.current.changeReason("需要访问客户数据"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
  });

  test("FF-5: 限时授权仅在过期时间为未来时才能提交", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => catalogResponse()));
    const { result } = await renderReadyForm("");

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["reader"]));
    await waitFor(() => expect(result.current.selectedApproverUserIds.length).toBeGreaterThan(0));
    act(() => result.current.changeReason("需要访问客户数据"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));

    act(() => result.current.changeGrantType("timed"));
    // 未填过期时间: 不能提交, 但也不算"过去"错误。
    expect(result.current.canSubmit).toBe(false);
    expect(result.current.expiresAtError).toBe(false);

    act(() => result.current.changeExpiresAt(new Date(Date.now() - 3_600_000).toISOString()));
    expect(result.current.canSubmit).toBe(false);
    expect(result.current.expiresAtError).toBe(true);

    act(() => result.current.changeExpiresAt(new Date(Date.now() + 3_600_000).toISOString()));
    expect(result.current.expiresAtError).toBe(false);
    expect(result.current.canSubmit).toBe(true);
  });

  test("FF-09: direct 与 authorization group 的覆盖关系不受操作顺序影响且提交载荷一致", async () => {
    const catalog = scopedCatalog({
      authorization_groups: [
        {
          id: 11,
          app_key: "crm",
          key: "customer-reader",
          kind: "role",
          name: "客户查看",
          grants: [{ permission_key: "customer.read", scope_key: "SELF" }],
        },
      ],
    });
    const submittedPayloads: unknown[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse(catalog);
      }
      if (String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        submittedPayloads.push(JSON.parse(String(init.body)));
        return jsonResponse({ access_request: { id: submittedPayloads.length } }, 201);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    const permission = result.current.ungroupedPermissions[0];
    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.selectedPermissionKeys).toEqual([directGrantSelectionKey("customer.read", "SELF")]);

    act(() => result.current.changeAuthorizationGroupKeys(["customer-reader"]));
    expect(result.current.selectedPermissionKeys).toEqual([]);

    act(() => result.current.changeReason("申请客户查看权限"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(submittedPayloads).toHaveLength(1));
    await waitFor(() => expect(result.current.authorizationGroupKeys).toEqual([]));

    // 反过来先选权限组再勾同一项直接权限: 权限组已覆盖它, 展示态本就是勾选, 因此不会重复进载荷。
    act(() => result.current.changeAuthorizationGroupKeys(["customer-reader"]));
    act(() => result.current.selectPermissionKeys([directGrantSelectionKey("customer.read", "SELF")]));
    expect(result.current.selectedPermissionKeys).toEqual([]);
    expect(result.current.groupCoveredSelectionKeys).toEqual([directGrantSelectionKey("customer.read", "SELF")]);

    act(() => result.current.changeReason("申请客户查看权限"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(submittedPayloads).toHaveLength(2));
    await waitFor(() => expect(result.current.authorizationGroupKeys).toEqual([]));

    expect(submittedPayloads[1]).toEqual(submittedPayloads[0]);

    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.selectedPermissionKeys).toHaveLength(1);
  });

  test("取消权限组覆盖的权限时把权限组落地成逐项直接申请", async () => {
    const catalog = scopedCatalog({
      ungrouped_permissions: [
        {
          id: 101,
          app_key: "crm",
          key: "customer.read",
          name: "查看客户",
          scopes: [{ key: "SELF", name: "本人" }],
        },
        {
          id: 102,
          app_key: "crm",
          key: "customer.export",
          name: "导出客户",
          scopes: [{ key: "SELF", name: "本人" }],
        },
      ],
      authorization_groups: [
        {
          id: 11,
          app_key: "crm",
          key: "customer-reader",
          kind: "role",
          name: "客户查看",
          grants: [
            { permission_key: "customer.read", scope_key: "SELF" },
            { permission_key: "customer.export", scope_key: "SELF" },
            // 目录里没有这一项: 当前用户不能单独申请, 落地时只能丢弃。
            { permission_key: "customer.delete", scope_key: "ALL" },
          ],
        },
      ],
    });
    const submittedPayloads: unknown[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse(catalog);
      }
      if (String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        submittedPayloads.push(JSON.parse(String(init.body)));
        return jsonResponse({ access_request: { id: 1 } }, 201);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["customer-reader"]));
    expect(result.current.groupCoveredSelectionKeys).toHaveLength(3);

    const readPermission = result.current.ungroupedPermissions.find((item) => item.key === "customer.read");
    act(() => result.current.changePermissionScope(readPermission!, "SELF"));

    // 权限组整体授予, 少一项就不再是它: 权限组目标清空, 其余可申请的覆盖权限转成直接申请。
    expect(result.current.authorizationGroupKeys).toEqual([]);
    expect(result.current.selectedPermissionKeys).toEqual([directGrantSelectionKey("customer.export", "SELF")]);
    expect(result.current.toastMessageKey).toBe("portal.request.groupMaterializedPartially");

    act(() => result.current.changeReason("只保留导出客户"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(submittedPayloads).toHaveLength(1));

    expect(submittedPayloads[0]).toMatchObject({
      authorization_group_keys: [],
      direct_grants: [{ permission: "customer.export", scope: "SELF" }],
    });
  });

  test("重新选中权限组后覆盖的权限重回覆盖态, 载荷不重复下发", async () => {
    const catalog = scopedCatalog({
      authorization_groups: [
        {
          id: 11,
          app_key: "crm",
          key: "customer-reader",
          kind: "role",
          name: "客户查看",
          grants: [{ permission_key: "customer.read", scope_key: "SELF" }],
        },
      ],
    });
    const submittedPayloads: unknown[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse(catalog);
      }
      if (String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        submittedPayloads.push(JSON.parse(String(init.body)));
        return jsonResponse({ access_request: { id: 1 } }, 201);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["customer-reader"]));
    const permission = result.current.ungroupedPermissions[0];
    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.authorizationGroupKeys).toEqual([]);
    expect(result.current.selectedPermissionKeys).toEqual([]);
    expect(result.current.toastMessageKey).toBe("portal.request.groupMaterialized");

    // 重新勾上这项权限, 再把权限组选回来: 覆盖关系恢复, 直接权限不再重复下发。
    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.selectedPermissionKeys).toEqual([directGrantSelectionKey("customer.read", "SELF")]);
    expect(result.current.toastMessageKey).toBe("");

    act(() => result.current.changeAuthorizationGroupKeys(["customer-reader"]));
    expect(result.current.selectedPermissionKeys).toEqual([]);

    act(() => result.current.changeReason("申请客户查看权限"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(submittedPayloads).toHaveLength(1));

    expect(submittedPayloads[0]).toMatchObject({
      authorization_group_keys: ["customer-reader"],
      direct_grants: [],
    });
  });

  test("多个权限组同时选中: 覆盖范围取并集, 被覆盖的直接权限不重复下发", async () => {
    const catalog = scopedCatalog({
      ungrouped_permissions: [
        { id: 101, app_key: "crm", key: "customer.read", name: "查看客户", scopes: [{ key: "SELF", name: "本人" }] },
        { id: 102, app_key: "crm", key: "customer.export", name: "导出客户", scopes: [{ key: "SELF", name: "本人" }] },
        { id: 103, app_key: "crm", key: "customer.audit", name: "审计客户", scopes: [{ key: "SELF", name: "本人" }] },
      ],
      authorization_groups: [
        {
          id: 11,
          app_key: "crm",
          key: "customer-reader",
          kind: "role",
          name: "客户查看",
          grants: [{ permission_key: "customer.read", scope_key: "SELF" }],
        },
        {
          id: 12,
          app_key: "crm",
          key: "customer-exporter",
          kind: "role",
          name: "客户导出",
          grants: [{ permission_key: "customer.export", scope_key: "SELF" }],
        },
      ],
    });
    const submittedPayloads: unknown[] = [];
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse(catalog);
      }
      if (String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        submittedPayloads.push(JSON.parse(String(init.body)));
        return jsonResponse({ access_request: { id: 1 } }, 201);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["customer-reader", "customer-exporter"]));
    expect(result.current.groupCoveredSelectionKeys).toEqual([
      directGrantSelectionKey("customer.read", "SELF"),
      directGrantSelectionKey("customer.export", "SELF"),
    ]);

    const auditPermission = result.current.ungroupedPermissions.find((item) => item.key === "customer.audit");
    act(() => result.current.changePermissionScope(auditPermission!, "SELF"));
    // 只加了一项没被任何权限组覆盖的权限: 两个权限组都留着, 不触发落地。
    expect(result.current.authorizationGroupKeys).toEqual(["customer-reader", "customer-exporter"]);
    expect(result.current.toastMessageKey).toBe("");

    act(() => result.current.changeReason("同时申请查看与导出"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(submittedPayloads).toHaveLength(1));

    expect(submittedPayloads[0]).toMatchObject({
      authorization_group_keys: ["customer-reader", "customer-exporter"],
      direct_grants: [{ permission: "customer.audit", scope: "SELF" }],
    });
  });

  test("FF-10: group 只按 grants 的 MANAGED_USERS 实际范围阻止 owner 回退", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(scopedCatalog({
      authorization_groups: [
        {
          id: 11,
          app_key: "crm",
          key: "managed-reader",
          kind: "role",
          name: "下级查看",
          approver_resolution_status: "direct_manager_missing",
          default_approver_user_ids: [],
          grants: [{ permission_key: "customer.read", scope_key: "MANAGED_USERS" }],
        },
      ],
    }))));
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["managed-reader"]));
    await waitFor(() => expect(result.current.selectedApproverUserIds).toEqual([]));
    expect(result.current.toastMessageKey).toBe("portal.request.approverMissing");

    act(() => result.current.toggleApprover("boss"));
    act(() => result.current.changeReason("查看下级客户"));
    expect(result.current.selectedApproverUserIds).toEqual(["boss"]);
    expect(result.current.canSubmit).toBe(false);
  });

  test("FF-10: direct 只按本次选中的 MANAGED_USERS 范围判断审批路径", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(scopedCatalog({
      ungrouped_permissions: [
        {
          id: 101,
          app_key: "crm",
          key: "customer.read",
          name: "查看客户",
          scopes: [
            { key: "SELF", name: "本人" },
            { key: "MANAGED_USERS", name: "下级用户" },
          ],
          approver_resolution_status: "direct_manager_missing",
          default_approver_user_ids: [],
        },
      ],
    }))));
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    const permission = result.current.ungroupedPermissions[0];
    act(() => result.current.changePermissionScope(permission, "SELF"));
    await waitFor(() => expect(result.current.selectedApproverUserIds).toEqual(["boss"]));
    expect(result.current.toastMessageKey).toBe("");

    act(() => result.current.changePermissionScope(permission, "MANAGED_USERS"));
    await waitFor(() => expect(result.current.selectedApproverUserIds).toEqual([]));
    expect(result.current.toastMessageKey).toBe("portal.request.approverMissing");
  });

  test("FF-23: 合法 key 含旧分隔符时仍按结构化二元组无损提交", async () => {
    const permissionKey = "reports::scope::view";
    const scopeKey = "SELF::scope::own";
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse(scopedCatalog({
          ungrouped_permissions: [
            { id: 101, app_key: "crm", key: permissionKey, name: "查看报告", scopes: [{ key: scopeKey, name: "本人" }] },
          ],
        }));
      }
      if (String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        return jsonResponse({ ok: true });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changePermissionScope(result.current.ungroupedPermissions[0], scopeKey));
    act(() => result.current.changeReason("查看报告"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));

    const requestInit = fetchMock.mock.calls.find(
      ([input, init]) => String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST",
    )?.[1];
    expect(JSON.parse(String(requestInit?.body))).toMatchObject({
      direct_grants: [{ permission: permissionKey, scope: scopeKey }],
    });
    expect(new Headers(requestInit?.headers).get("Idempotency-Key")).toMatch(/^[0-9a-f-]{36}$/);
  });

  test("BF-15: 网络失败后重试复用同一 Idempotency-Key", async () => {
    const requestHeaders: string[] = [];
    let submitAttempts = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      if (String(input) === "/portal/api/v1/request-catalog") {
        return jsonResponse(scopedCatalog());
      }
      if (String(input) === "/portal/api/v1/me/access-requests" && init?.method === "POST") {
        requestHeaders.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
        submitAttempts += 1;
        if (submitAttempts === 1) {
          throw new TypeError("network interrupted");
        }
        return jsonResponse({ access_request: { id: 42 } });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.changeAuthorizationGroupKeys(["reader"]));
    act(() => result.current.changeReason("幂等重试"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.submitErrorMessage).toContain("网络连接失败"));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.toastMessageKey).toBe("portal.request.submitted"));

    expect(requestHeaders).toHaveLength(2);
    expect(requestHeaders[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(requestHeaders[1]).toBe(requestHeaders[0]);
  });

  test("FF-23: catalog 成功响应缺少数组契约时进入明确错误态", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse({})));
    const { result } = renderHook(() => useAccessRequestForm(), { wrapper });

    await waitFor(() => expect(result.current.catalogErrorMessage).toContain("申请目录.apps 必须为数组"));
    expect(result.current.apps).toEqual([]);
  });

  test("FF-23: catalog 行结构错误时拒绝消费", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(scopedCatalog({
      apps: [{ id: "1", app_key: "crm", name: "CRM", alias: "" }],
    }))));
    const { result } = renderHook(() => useAccessRequestForm(), { wrapper });

    await waitFor(() => expect(result.current.catalogErrorMessage).toContain("申请目录.apps[0].id 必须为有限数字"));
  });

  test("FF-23: 直接权限选择不被静默截断，审批人和理由仍受服务端同值上限约束", async () => {
    const approverOptions = Array.from({ length: ACCESS_REQUEST_MAX_APPROVERS + 1 }, (_, index) => ({
      user_id: `approver-${index}`,
      name: `审批人 ${index}`,
    }));
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(scopedCatalog({
      apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "", default_approver_user_ids: [] }],
      approver_options: approverOptions,
      ungrouped_permissions: [],
    }))));
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.selectPermissionKeys(
      Array.from({ length: 51 }, (_, index) => directGrantSelectionKey(`permission-${index}`, "SELF")),
    ));
    for (const option of approverOptions) {
      act(() => result.current.toggleApprover(option.user_id));
    }
    act(() => result.current.changeReason("理".repeat(ACCESS_REQUEST_MAX_REASON_LENGTH + 1)));

    expect(result.current.selectedPermissionKeys).toHaveLength(51);
    expect(result.current.selectedApproverUserIds).toHaveLength(ACCESS_REQUEST_MAX_APPROVERS);
    expect(result.current.reason).toHaveLength(ACCESS_REQUEST_MAX_REASON_LENGTH);
  });
});

/** 目标可编辑到什么程度由后端 submission_validation 决定, 四种申请类型各不相同。 */
describe("useAccessRequestForm 按申请类型约束申请目标", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const READ_KEY = directGrantSelectionKey("orders.read", "SELF");
  const EXPORT_KEY = directGrantSelectionKey("orders.export", "SELF");
  const AUDIT_KEY = directGrantSelectionKey("orders.audit", "SELF");

  function lifecycleCatalog() {
    return scopedCatalog({
      ungrouped_permissions: [
        { id: 101, app_key: "crm", key: "orders.read", name: "查看订单", scopes: [{ key: "SELF", name: "本人" }] },
        { id: 102, app_key: "crm", key: "orders.export", name: "导出订单", scopes: [{ key: "SELF", name: "本人" }] },
        { id: 103, app_key: "crm", key: "orders.audit", name: "审计订单", scopes: [{ key: "SELF", name: "本人" }] },
      ],
      authorization_groups: [
        {
          id: 11,
          app_key: "crm",
          key: "reader",
          kind: "role",
          name: "只读",
          requestable: true,
          grants: [
            { permission_key: "orders.read", scope_key: "SELF" },
            { permission_key: "orders.export", scope_key: "SELF" },
          ],
        },
      ],
    });
  }

  function expandedGrant(permission: string, sourceType: string, sourceKey: string | null) {
    return {
      permission,
      scope: "SELF",
      source_type: sourceType,
      source_key: sourceKey,
      permission_name: permission,
      permission_name_en: permission,
      scope_name: "本人",
      scope_name_en: "Self",
    };
  }

  /** 一条 reader 权限组 + 一项直接权限的当前授权, 供 change / revoke / renew 当基础授权。 */
  function lifecycleGrantList() {
    return {
      data: [
        {
          grant_id: 7,
          grant_revision: 3,
          app_key: "crm",
          app_name: "CRM",
          app_alias: "",
          grant_type: "timed",
          grant_expires_at: "2030-01-01T00:00:00+00:00",
          grant_version: 5,
          catalog_version: 2,
          snapshot_version: "v1",
          groups: [{ key: "reader", kind: "role", name: "只读" }],
          grants: [
            expandedGrant("orders.read", "group", "reader"),
            expandedGrant("orders.export", "group", "reader"),
            expandedGrant("orders.audit", "direct", null),
          ],
        },
      ],
      pagination: { page: 1, page_size: 100, total_items: 1, total_pages: 1 },
    };
  }

  function stubLifecycleFetch() {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url === "/portal/api/v1/request-catalog") {
        return jsonResponse(lifecycleCatalog());
      }
      if (url === "/portal/api/v1/me/grants?page=1&page_size=100") {
        return jsonResponse(lifecycleGrantList());
      }
      throw new Error(`Unexpected fetch: ${url}`);
    }));
  }

  async function renderFormWithBaseGrant(requestType: "change" | "revoke" | "renew") {
    stubLifecycleFetch();
    const view = await renderReadyForm();
    act(() => view.result.current.changeRequestType(requestType));
    await waitFor(() => expect(view.result.current.currentGrants).toHaveLength(1));
    act(() => view.result.current.changeBaseGrantId("7"));
    await waitFor(() => expect(view.result.current.authorizationGroupKeys).toEqual(["reader"]));
    return view;
  }

  function ordersPermission(view: Awaited<ReturnType<typeof renderReadyForm>>, key: string) {
    const permission = view.result.current.ungroupedPermissions.find((item) => item.key === key);
    expect(permission).toBeDefined();
    return permission!;
  }

  test("grant: 取消权限组覆盖的权限把该组落地成逐项直接申请", async () => {
    stubLifecycleFetch();
    const view = await renderReadyForm();

    act(() => view.result.current.changeAppKey("crm"));
    act(() => view.result.current.changeAuthorizationGroupKeys(["reader"]));
    act(() => view.result.current.changePermissionScope(ordersPermission(view, "orders.read"), "SELF"));

    expect(view.result.current.authorizationGroupKeys).toEqual([]);
    expect(view.result.current.selectedPermissionKeys).toEqual([EXPORT_KEY]);
    expect(view.result.current.toastMessageKey).toBe("portal.request.groupMaterialized");
  });

  test("change: 取消权限组覆盖的权限把该组落地, 原有直接权限保留", async () => {
    const view = await renderFormWithBaseGrant("change");
    expect(view.result.current.selectedPermissionKeys).toEqual([AUDIT_KEY]);
    expect(view.result.current.groupCoveredSelectionKeys).toEqual([READ_KEY, EXPORT_KEY]);

    act(() => view.result.current.changePermissionScope(ordersPermission(view, "orders.read"), "SELF"));

    expect(view.result.current.authorizationGroupKeys).toEqual([]);
    expect(view.result.current.selectedPermissionKeys).toEqual([AUDIT_KEY, EXPORT_KEY]);
    expect(view.result.current.toastMessageKey).toBe("portal.request.groupMaterialized");
  });

  test("revoke: 取消权限组覆盖的权限整组撤销, 不落地成直接权限", async () => {
    const view = await renderFormWithBaseGrant("revoke");

    act(() => view.result.current.changePermissionScope(ordersPermission(view, "orders.read"), "SELF"));

    // 撤销目标是"保留下来的授权", 必须是基础授权的子集: 落地会引入基础授权里没有的直接权限。
    expect(view.result.current.authorizationGroupKeys).toEqual([]);
    expect(view.result.current.selectedPermissionKeys).toEqual([AUDIT_KEY]);
    expect(view.result.current.groupCoveredSelectionKeys).toEqual([]);
    expect(view.result.current.toastMessageKey).toBe("portal.request.groupRevokedWhole");
  });

  test("revoke: 取消直接权限只影响这一项, 权限组照旧保留", async () => {
    const view = await renderFormWithBaseGrant("revoke");

    act(() => view.result.current.changePermissionScope(ordersPermission(view, "orders.audit"), "SELF"));

    expect(view.result.current.authorizationGroupKeys).toEqual(["reader"]);
    expect(view.result.current.selectedPermissionKeys).toEqual([]);
    expect(view.result.current.toastMessageKey).toBe("");
  });

  test("renew: 目标完全不可编辑, 任何改动都直接失败", async () => {
    const view = await renderFormWithBaseGrant("renew");
    expect(view.result.current.selectedPermissionKeys).toEqual([AUDIT_KEY]);

    expect(() =>
      act(() => view.result.current.changePermissionScope(ordersPermission(view, "orders.audit"), "SELF")),
    ).toThrow("续期申请不能修改申请目标");
    expect(() => act(() => view.result.current.selectPermissionKeys([READ_KEY]))).toThrow(
      "续期申请不能修改申请目标",
    );
    expect(() => act(() => view.result.current.clearPermissionKeys([AUDIT_KEY]))).toThrow(
      "续期申请不能修改申请目标",
    );
    expect(() => act(() => view.result.current.changeAuthorizationGroupKeys([]))).toThrow(
      "续期申请不能修改申请目标",
    );

    expect(view.result.current.authorizationGroupKeys).toEqual(["reader"]);
    expect(view.result.current.selectedPermissionKeys).toEqual([AUDIT_KEY]);
  });
});
