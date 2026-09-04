import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../../i18n/I18nProvider";
import { RequestTargetPicker } from "./RequestTargetPicker";

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
    const onAuthorizationGroupKeysChange = vi.fn();
    render(
      <I18nProvider>
        <RequestTargetPicker
          appKey="crm"
          apps={[{ id: 1, app_key: "crm", name: "CRM", alias: "" }]}
          authorizationGroupKeys={["sales-reader"]}
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
          onAuthorizationGroupKeysChange={onAuthorizationGroupKeysChange}
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
    expect(within(groupPicker).getByRole("checkbox", { name: "销售只读" })).toBeChecked();

    fireEvent.click(within(groupPicker).getByRole("checkbox", { name: "订单运营包" }));
    expect(onAuthorizationGroupKeysChange).toHaveBeenLastCalledWith(["sales-reader", "order-ops"]);

    fireEvent.click(within(groupPicker).getByRole("checkbox", { name: "销售只读" }));
    expect(onAuthorizationGroupKeysChange).toHaveBeenLastCalledWith([]);
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
