import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, test, vi } from "vitest";

import { directGrantSelectionKey } from "./accessRequestSelection";
import { useAccessRequestForm } from "./useAccessRequestForm";
import { parseAccessRequestPrefill, useAccessRequestPrefill } from "./useAccessRequestPrefill";

const CATALOG_URL = "/portal/api/v1/request-catalog";
const GRANTS_URL = "/portal/api/v1/me/grants?page=1&page_size=100";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function catalog() {
  return {
    apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "客户管理", default_approver_user_ids: ["boss"] }],
    approver_options: [{ user_id: "boss", name: "老板" }],
    authorization_groups: [
      {
        id: 11,
        app_key: "crm",
        key: "reader",
        kind: "role",
        name: "只读",
        requestable: true,
        grants: [{ permission_key: "customer.write", scope_key: "SELF" }],
      },
    ],
    permission_groups: [],
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
        key: "customer.write",
        name: "编辑客户",
        scopes: [{ key: "SELF", name: "本人" }],
      },
    ],
  };
}

function grantList(overrides: Record<string, unknown> = {}) {
  return {
    data: [
      {
        grant_id: 7,
        grant_revision: 3,
        app_key: "crm",
        app_name: "CRM",
        app_alias: "客户管理",
        grant_type: "permanent",
        grant_expires_at: null,
        grant_version: 5,
        catalog_version: 2,
        snapshot_version: "v1",
        groups: [{ key: "reader", kind: "role", name: "只读" }],
        ...overrides,
        grants: [
          {
            permission: "customer.read",
            scope: "SELF",
            source_type: "direct",
            source_key: null,
            permission_name: "查看客户",
            permission_name_en: "View customers",
            scope_name: "本人",
            scope_name_en: "Self",
          },
          {
            permission: "customer.write",
            scope: "SELF",
            source_type: "group",
            source_key: "reader",
            permission_name: "编辑客户",
            permission_name_en: "Edit customers",
            scope_name: "本人",
            scope_name_en: "Self",
          },
        ],
      },
    ],
    pagination: { page: 1, page_size: 100, total_items: 1, total_pages: 1 },
  };
}

function stubFetch(grants = grantList()) {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url === CATALOG_URL) {
      return jsonResponse(catalog());
    }
    if (url === GRANTS_URL) {
      return jsonResponse(grants);
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** 与 AccessRequestForm 一致的接线: 路由 state -> 预填 -> 表单, 应用后清空 history state。 */
function usePrefilledForm() {
  const location = useLocation();
  const { prefill, clearRouterState } = useAccessRequestPrefill();
  const form = useAccessRequestForm("", { prefill, onPrefillApplied: clearRouterState });
  return { form, locationState: location.state };
}

function renderPrefilledForm(state: unknown) {
  function wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return createElement(
      MemoryRouter,
      { initialEntries: [{ pathname: "/portal/request", state }] },
      createElement(QueryClientProvider, { client }, children),
    );
  }
  return renderHook(() => usePrefilledForm(), { wrapper });
}

describe("parseAccessRequestPrefill", () => {
  test("没有路由 state 或没有预填字段时不产生预填", () => {
    expect(parseAccessRequestPrefill(null)).toBeNull();
    expect(parseAccessRequestPrefill(undefined)).toBeNull();
    expect(parseAccessRequestPrefill({ from: "/portal" })).toBeNull();
  });

  test("预填形状不符合约定时直接抛错", () => {
    expect(() => parseAccessRequestPrefill("change")).toThrow("申请表路由 state 必须是对象");
    expect(() => parseAccessRequestPrefill({ accessRequestPrefill: "7" })).toThrow("必须是对象");
    expect(() =>
      parseAccessRequestPrefill({ accessRequestPrefill: { requestType: "renew", baseGrantId: "7" } }),
    ).toThrow("requestType 必须是 change");
    expect(() =>
      parseAccessRequestPrefill({ accessRequestPrefill: { requestType: "change", baseGrantId: "" } }),
    ).toThrow("baseGrantId 必须是非空字符串");
    expect(() =>
      parseAccessRequestPrefill({ accessRequestPrefill: { requestType: "change", baseGrantId: "7", appKey: "crm" } }),
    ).toThrow("含未知字段：appKey");
  });
});

describe("useAccessRequestPrefill", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("基础授权加载完成后按预填选中该授权, 并清空路由 state", async () => {
    stubFetch();
    const { result } = renderPrefilledForm({ accessRequestPrefill: { requestType: "change", baseGrantId: "7" } });

    expect(result.current.form.requestType).toBe("change");
    await waitFor(() => expect(result.current.form.baseGrantId).toBe("7"));

    expect(result.current.form.appKey).toBe("crm");
    expect(result.current.form.authorizationGroupKey).toBe("reader");
    expect(result.current.form.selectedPermissionKeys).toEqual([directGrantSelectionKey("customer.read", "SELF")]);
    // 权限组带来的权限走覆盖态: 展示为勾选, 但不重复进直接权限。
    expect(result.current.form.groupCoveredSelectionKeys).toEqual([directGrantSelectionKey("customer.write", "SELF")]);
    expect(result.current.form.grantType).toBe("permanent");
    expect(result.current.form.prefillErrorMessageKey).toBe("");
    await waitFor(() => expect(result.current.locationState).toBeNull());
  });

  test("取消预填进来的权限组权限时权限组落地, 直接权限原样保留", async () => {
    stubFetch();
    const { result } = renderPrefilledForm({ accessRequestPrefill: { requestType: "change", baseGrantId: "7" } });

    await waitFor(() => expect(result.current.form.authorizationGroupKey).toBe("reader"));
    const writePermission = result.current.form.ungroupedPermissions.find(
      (permission) => permission.key === "customer.write",
    );
    expect(writePermission).toBeDefined();

    act(() => result.current.form.changePermissionScope(writePermission!, "SELF"));

    expect(result.current.form.authorizationGroupKey).toBe("");
    expect(result.current.form.groupCoveredSelectionKeys).toEqual([]);
    expect(result.current.form.selectedPermissionKeys).toEqual([directGrantSelectionKey("customer.read", "SELF")]);
    expect(result.current.form.toastMessageKey).toBe("portal.request.groupMaterialized");
  });

  test("基础授权含多个权限组时给出可见错误而不是只取第一个", async () => {
    stubFetch(
      grantList({
        groups: [
          { key: "reader", kind: "role", name: "只读" },
          { key: "writer", kind: "role", name: "读写" },
        ],
      }),
    );
    const { result } = renderPrefilledForm({ accessRequestPrefill: { requestType: "change", baseGrantId: "7" } });

    await waitFor(() =>
      expect(result.current.form.prefillErrorMessageKey).toBe("portal.request.prefillMultiGroupUnsupported"),
    );
    expect(result.current.form.baseGrantId).toBe("");
    expect(result.current.form.authorizationGroupKey).toBe("");
    expect(result.current.form.selectedPermissionKeys).toEqual([]);
  });

  test("预填的授权不在当前授权列表里时给出可见错误", async () => {
    stubFetch();
    const { result } = renderPrefilledForm({ accessRequestPrefill: { requestType: "change", baseGrantId: "999" } });

    await waitFor(() =>
      expect(result.current.form.prefillErrorMessageKey).toBe("portal.request.prefillBaseGrantMissing"),
    );
    expect(result.current.form.baseGrantId).toBe("");
    expect(result.current.form.requestType).toBe("change");
    await waitFor(() => expect(result.current.locationState).toBeNull());
  });

  test("没有路由 state 时表单保持默认态", async () => {
    const fetchMock = stubFetch();
    const { result } = renderPrefilledForm(undefined);

    await waitFor(() => expect(result.current.form.apps).toHaveLength(1));

    expect(result.current.form.requestType).toBe("grant");
    expect(result.current.form.baseGrantId).toBe("");
    expect(result.current.form.prefillErrorMessageKey).toBe("");
    // 申请新增授权不需要基础授权列表, 不应该多打一次授权接口。
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual([CATALOG_URL]);
  });
});
