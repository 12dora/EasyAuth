import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import {
  ACCESS_REQUEST_MAX_APPROVERS,
  ACCESS_REQUEST_MAX_DIRECT_GRANTS,
  ACCESS_REQUEST_MAX_REASON_LENGTH,
  directGrantSelectionKey,
  useAccessRequestForm,
} from "./useAccessRequestForm";

function catalogResponse() {
  return jsonResponse(
    {
      apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["me", "boss"] }],
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
    apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: ["boss"] }],
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
    act(() => result.current.changeAuthorizationGroupKey("reader"));
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
    act(() => result.current.changeAuthorizationGroupKey("reader"));
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

  test("FF-09: direct 与 authorization group 的覆盖关系不受操作顺序影响", async () => {
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
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(catalog)));
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    const permission = result.current.ungroupedPermissions[0];
    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.selectedPermissionKeys).toEqual([directGrantSelectionKey("customer.read", "SELF")]);

    act(() => result.current.changeAuthorizationGroupKey("customer-reader"));
    expect(result.current.selectedPermissionKeys).toEqual([]);

    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.selectedPermissionKeys).toEqual([]);

    act(() => result.current.changeAuthorizationGroupKey(""));
    act(() => result.current.changePermissionScope(permission, "SELF"));
    expect(result.current.selectedPermissionKeys).toHaveLength(1);
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
    act(() => result.current.changeAuthorizationGroupKey("managed-reader"));
    await waitFor(() => expect(result.current.selectedApproverUserIds).toEqual([]));
    expect(result.current.toastMessageKey).toBe("portal.request.approverMissing");
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

    const requestInit = fetchMock.mock.calls[1][1];
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
    act(() => result.current.changeAuthorizationGroupKey("reader"));
    act(() => result.current.changeReason("幂等重试"));
    await waitFor(() => expect(result.current.canSubmit).toBe(true));
    act(() => result.current.submit());
    await waitFor(() => expect(result.current.submitErrorMessage).toContain("network interrupted"));
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
      apps: [{ id: "1", app_key: "crm", name: "CRM" }],
    }))));
    const { result } = renderHook(() => useAccessRequestForm(), { wrapper });

    await waitFor(() => expect(result.current.catalogErrorMessage).toContain("申请目录.apps[0].id 必须为有限数字"));
  });

  test("FF-23: direct、审批人和理由均受服务端同值上限约束", async () => {
    const approverOptions = Array.from({ length: ACCESS_REQUEST_MAX_APPROVERS + 1 }, (_, index) => ({
      user_id: `approver-${index}`,
      name: `审批人 ${index}`,
    }));
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => jsonResponse(scopedCatalog({
      apps: [{ id: 1, app_key: "crm", name: "CRM", default_approver_user_ids: [] }],
      approver_options: approverOptions,
      ungrouped_permissions: [],
    }))));
    const { result } = await renderReadyForm();

    act(() => result.current.changeAppKey("crm"));
    act(() => result.current.selectPermissionKeys(
      Array.from({ length: ACCESS_REQUEST_MAX_DIRECT_GRANTS + 1 }, (_, index) => directGrantSelectionKey(`permission-${index}`, "SELF")),
    ));
    for (const option of approverOptions) {
      act(() => result.current.toggleApprover(option.user_id));
    }
    act(() => result.current.changeReason("理".repeat(ACCESS_REQUEST_MAX_REASON_LENGTH + 1)));

    expect(result.current.selectedPermissionKeys).toHaveLength(ACCESS_REQUEST_MAX_DIRECT_GRANTS);
    expect(result.current.selectedApproverUserIds).toHaveLength(ACCESS_REQUEST_MAX_APPROVERS);
    expect(result.current.reason).toHaveLength(ACCESS_REQUEST_MAX_REASON_LENGTH);
  });
});
