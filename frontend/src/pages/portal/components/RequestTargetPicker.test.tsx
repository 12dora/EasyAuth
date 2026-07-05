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
          apps={[{ id: 1, app_key: "crm", name: "CRM" }]}
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
});
