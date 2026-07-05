import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { useAccessRequestForm } from "./useAccessRequestForm";

function catalogResponse() {
  return new Response(
    JSON.stringify({
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
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
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
});
