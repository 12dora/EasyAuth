import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../../i18n/I18nProvider";
import type { RevokeBaseGrantSnapshot } from "../hooks/accessRequestTargetLock";
import type { AuthorizationGroupItem } from "../hooks/accessRequestTypes";
import { RequestTargetPicker } from "./RequestTargetPicker";

/**
 * 受控组件必须由持有状态的一方回灌 props 才能验证多选语义:
 * 只断言回调参数会把"第二次点击基于第一次结果"这件事漏掉。
 */
function StatefulGroupPicker({
  initialGroupKeys,
  authorizationGroups,
  revokeBaseGrant = null,
}: {
  initialGroupKeys: string[];
  authorizationGroups: AuthorizationGroupItem[];
  revokeBaseGrant?: RevokeBaseGrantSnapshot | null;
}) {
  const [authorizationGroupKeys, setAuthorizationGroupKeys] = useState(initialGroupKeys);
  return (
    <I18nProvider>
      <RequestTargetPicker
        appKey="crm"
        apps={[{ id: 1, app_key: "crm", name: "CRM", alias: "" }]}
        authorizationGroupKeys={authorizationGroupKeys}
        authorizationGroups={authorizationGroups}
        permissionGroups={[]}
        ungroupedPermissions={[]}
        selectedPermissionKeys={[]}
        revokeBaseGrant={revokeBaseGrant}
        expandedGroupKeys={[]}
        catalogIsLoading={false}
        catalogErrorMessage=""
        onAppKeyChange={vi.fn()}
        onAuthorizationGroupKeysChange={setAuthorizationGroupKeys}
        onPermissionScopeChange={vi.fn()}
        onPermissionGroupScopeChange={vi.fn()}
        onSelectPermissionKeys={vi.fn()}
        onClearPermissionKeys={vi.fn()}
        onExpandGroups={vi.fn()}
        onCollapseGroups={vi.fn()}
        onToggleGroup={vi.fn()}
      />
    </I18nProvider>
  );
}

function checkedGroupNames() {
  const groupPicker = screen.getByRole("group", { name: "可申请权限组" });
  return within(groupPicker)
    .getAllByRole("checkbox")
    .filter((checkbox) => (checkbox as HTMLInputElement).checked)
    .map((checkbox) => (checkbox as HTMLInputElement).value);
}

describe("RequestTargetPicker", () => {
  test("FF-10: 直接权限字段使用 group 语义并关联标题", () => {
    render(
      <I18nProvider>
        <RequestTargetPicker
          appKey="crm"
          apps={[{ id: 1, app_key: "crm", name: "CRM", alias: "" }]}
          authorizationGroupKeys={[]}
          authorizationGroups={[]}
          permissionGroups={[]}
          ungroupedPermissions={[]}
          selectedPermissionKeys={[]}
          expandedGroupKeys={[]}
          catalogIsLoading={false}
          catalogErrorMessage=""
          onAppKeyChange={vi.fn()}
          onAuthorizationGroupKeysChange={vi.fn()}
          onPermissionScopeChange={vi.fn()}
          onPermissionGroupScopeChange={vi.fn()}
          onSelectPermissionKeys={vi.fn()}
          onClearPermissionKeys={vi.fn()}
          onExpandGroups={vi.fn()}
          onCollapseGroups={vi.fn()}
          onToggleGroup={vi.fn()}
        />
      </I18nProvider>,
    );

    const group = screen.getByRole("group", { name: "直接权限" });
    const labelledBy = group.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy as string)).toHaveTextContent("直接权限");
  });

  test("权限组多选只展示本地化组名, 不带类别与 key", () => {
    render(
      <I18nProvider>
        <RequestTargetPicker
          appKey="crm"
          apps={[{ id: 1, app_key: "crm", name: "CRM", alias: "" }]}
          authorizationGroupKeys={[]}
          authorizationGroups={[
            { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", grants: [] },
            { id: 12, app_key: "crm", key: "order-ops", kind: "bundle", name: "订单运营包", grants: [] },
          ]}
          permissionGroups={[]}
          ungroupedPermissions={[]}
          selectedPermissionKeys={[]}
          expandedGroupKeys={[]}
          catalogIsLoading={false}
          catalogErrorMessage=""
          onAppKeyChange={vi.fn()}
          onAuthorizationGroupKeysChange={vi.fn()}
          onPermissionScopeChange={vi.fn()}
          onPermissionGroupScopeChange={vi.fn()}
          onSelectPermissionKeys={vi.fn()}
          onClearPermissionKeys={vi.fn()}
          onExpandGroups={vi.fn()}
          onCollapseGroups={vi.fn()}
          onToggleGroup={vi.fn()}
        />
      </I18nProvider>,
    );

    const groupPicker = screen.getByRole("group", { name: "可申请权限组" });
    expect(within(groupPicker).getByRole("checkbox", { name: "销售只读" })).toHaveAttribute("value", "sales-reader");
    expect(within(groupPicker).getByRole("checkbox", { name: "订单运营包" })).toHaveAttribute("value", "order-ops");
    expect(within(groupPicker).queryByRole("checkbox", { name: /\[|\(/ })).not.toBeInTheDocument();
  });

  test("权限组多选按整套集合回传, 勾选与取消都不丢掉其余已选组", () => {
    render(
      <StatefulGroupPicker
        initialGroupKeys={["sales-reader"]}
        authorizationGroups={[
          { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", grants: [] },
          { id: 12, app_key: "crm", key: "order-ops", kind: "bundle", name: "订单运营包", grants: [] },
        ]}
      />,
    );

    const groupPicker = screen.getByRole("group", { name: "可申请权限组" });
    expect(checkedGroupNames()).toEqual(["sales-reader"]);

    fireEvent.click(within(groupPicker).getByRole("checkbox", { name: "订单运营包" }));
    expect(checkedGroupNames()).toEqual(["sales-reader", "order-ops"]);

    // 取消其中一个只摘掉这一个: 上一次勾上的 order-ops 必须留着。
    fireEvent.click(within(groupPicker).getByRole("checkbox", { name: "销售只读" }));
    expect(checkedGroupNames()).toEqual(["order-ops"]);
  });

  test("撤销申请里基础授权之外的权限组不能勾选, 基础授权已有的组可取消也可勾回来", () => {
    render(
      <StatefulGroupPicker
        initialGroupKeys={["sales-reader"]}
        authorizationGroups={[
          { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", grants: [] },
          { id: 12, app_key: "crm", key: "order-ops", kind: "bundle", name: "订单运营包", grants: [] },
        ]}
        revokeBaseGrant={{ groupKeys: ["sales-reader"], directSelectionKeys: [] }}
      />,
    );

    const groupPicker = screen.getByRole("group", { name: "可申请权限组" });
    // 撤销目标是"撤销后保留下来的授权", 必须是基础授权的子集: 加进新权限组必被后端拒绝。
    expect(within(groupPicker).getByRole("checkbox", { name: "订单运营包" })).toBeDisabled();

    const baseGrantGroup = within(groupPicker).getByRole("checkbox", { name: "销售只读" });
    expect(baseGrantGroup).toBeEnabled();

    fireEvent.click(baseGrantGroup);
    expect(checkedGroupNames()).toEqual([]);

    fireEvent.click(baseGrantGroup);
    expect(checkedGroupNames()).toEqual(["sales-reader"]);
  });

  test("应用下拉展示别名: 有别名拼成「别名 (技术名)」, 没别名只显示技术名", () => {
    render(
      <I18nProvider>
        <RequestTargetPicker
          appKey="crm"
          apps={[
            { id: 1, app_key: "crm", name: "CRM", alias: "客户管理" },
            { id: 2, app_key: "billing", name: "Billing", alias: "" },
          ]}
          authorizationGroupKeys={[]}
          authorizationGroups={[]}
          permissionGroups={[]}
          ungroupedPermissions={[]}
          selectedPermissionKeys={[]}
          expandedGroupKeys={[]}
          catalogIsLoading={false}
          catalogErrorMessage=""
          onAppKeyChange={vi.fn()}
          onAuthorizationGroupKeysChange={vi.fn()}
          onPermissionScopeChange={vi.fn()}
          onPermissionGroupScopeChange={vi.fn()}
          onSelectPermissionKeys={vi.fn()}
          onClearPermissionKeys={vi.fn()}
          onExpandGroups={vi.fn()}
          onCollapseGroups={vi.fn()}
          onToggleGroup={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(screen.getByRole("option", { name: "客户管理 (CRM)" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Billing" })).toBeVisible();
  });
});
