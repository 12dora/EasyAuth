import { render, screen } from "@testing-library/react";
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
          authorizationGroupKey=""
          authorizationGroups={[]}
          permissionGroups={[]}
          ungroupedPermissions={[]}
          selectedPermissionKeys={[]}
          expandedGroupKeys={[]}
          catalogIsLoading={false}
          catalogErrorMessage=""
          onAppKeyChange={vi.fn()}
          onAuthorizationGroupKeyChange={vi.fn()}
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

    const group = screen.getByRole("group");
    const labelledBy = group.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy as string)).toHaveTextContent("直接权限");
  });

  test("权限组下拉只展示本地化组名, 不带类别与 key", () => {
    render(
      <I18nProvider>
        <RequestTargetPicker
          appKey="crm"
          apps={[{ id: 1, app_key: "crm", name: "CRM", alias: "" }]}
          authorizationGroupKey=""
          authorizationGroups={[
            { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读" },
            { id: 12, app_key: "crm", key: "order-ops", kind: "bundle", name: "订单运营包" },
          ]}
          permissionGroups={[]}
          ungroupedPermissions={[]}
          selectedPermissionKeys={[]}
          expandedGroupKeys={[]}
          catalogIsLoading={false}
          catalogErrorMessage=""
          onAppKeyChange={vi.fn()}
          onAuthorizationGroupKeyChange={vi.fn()}
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

    expect(screen.getByRole("option", { name: "销售只读" })).toHaveValue("sales-reader");
    expect(screen.getByRole("option", { name: "订单运营包" })).toHaveValue("order-ops");
    expect(screen.queryByRole("option", { name: /\[|\(/ })).not.toBeInTheDocument();
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
          authorizationGroupKey=""
          authorizationGroups={[]}
          permissionGroups={[]}
          ungroupedPermissions={[]}
          selectedPermissionKeys={[]}
          expandedGroupKeys={[]}
          catalogIsLoading={false}
          catalogErrorMessage=""
          onAppKeyChange={vi.fn()}
          onAuthorizationGroupKeyChange={vi.fn()}
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
