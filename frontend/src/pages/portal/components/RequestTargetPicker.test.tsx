import { screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import { useState, type ComponentProps } from "react";
import { describe, expect, test, vi } from "vitest";

import { renderWithAntd } from "../../../components/antd/testing";
import type { RevokeBaseGrantSnapshot } from "../hooks/accessRequestTargetLock";
import type { AuthorizationGroupItem } from "../hooks/accessRequestTypes";
import { RequestTargetPicker } from "./RequestTargetPicker";

type PickerProps = ComponentProps<typeof RequestTargetPicker>;

const CRM_GROUPS: AuthorizationGroupItem[] = [
  { id: 11, app_key: "crm", key: "sales-reader", kind: "role", name: "销售只读", grants: [] },
  { id: 12, app_key: "crm", key: "order-ops", kind: "bundle", name: "订单运营包", grants: [] },
];

function pickerProps(overrides: Partial<PickerProps> = {}): PickerProps {
  return {
    appKey: "crm",
    apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
    authorizationGroupKeys: [],
    authorizationGroups: [],
    permissionGroups: [],
    ungroupedPermissions: [],
    selectedPermissionKeys: [],
    expandedGroupKeys: [],
    catalogIsLoading: false,
    catalogErrorMessage: "",
    onAppKeyChange: vi.fn(),
    onAuthorizationGroupKeysChange: vi.fn(),
    onPermissionScopeChange: vi.fn(),
    onPermissionGroupScopeChange: vi.fn(),
    onSelectPermissionKeys: vi.fn(),
    onClearPermissionKeys: vi.fn(),
    onExpandGroups: vi.fn(),
    onCollapseGroups: vi.fn(),
    onToggleGroup: vi.fn(),
    ...overrides,
  };
}

/**
 * 受控组件必须由持有状态的一方回灌 props 才能验证多选语义:
 * 只断言回调参数会把"第二次点击基于第一次结果"这件事漏掉。
 */
function StatefulGroupPicker({
  initialGroupKeys,
  onChange,
  ...overrides
}: {
  initialGroupKeys: string[];
  onChange?: (groupKeys: string[]) => void;
} & Partial<PickerProps>) {
  const [authorizationGroupKeys, setAuthorizationGroupKeys] = useState(initialGroupKeys);
  return (
    <RequestTargetPicker
      {...pickerProps({ authorizationGroups: CRM_GROUPS, ...overrides })}
      authorizationGroupKeys={authorizationGroupKeys}
      onAuthorizationGroupKeysChange={(groupKeys) => {
        setAuthorizationGroupKeys(groupKeys);
        onChange?.(groupKeys);
      }}
    />
  );
}

function authorizationGroupCombobox(): HTMLElement {
  return screen.getByLabelText("可申请权限组");
}

/** 已挂载的权限组下拉面板; 还没点开过时返回 null(antd 的下拉是延迟挂载的 portal)。 */
function mountedDropdown(): HTMLElement | null {
  const listId = authorizationGroupCombobox().getAttribute("aria-controls") ?? "";
  const dropdown = document.getElementById(listId)?.closest(".ant-select-dropdown");
  return dropdown instanceof HTMLElement ? dropdown : null;
}

/** 点开(或复用已挂载的)权限组下拉。收起后 antd 仍保留面板, 因此选中态可以一直从这里读。 */
async function openAuthorizationGroups(user: UserEvent): Promise<HTMLElement> {
  const mounted = mountedDropdown();
  if (mounted) {
    return mounted;
  }
  const selector = authorizationGroupCombobox().closest(".ant-select")?.querySelector(".ant-select-selector");
  if (!(selector instanceof HTMLElement)) {
    throw new Error("「可申请权限组」不是 antd Select");
  }
  await user.click(selector);
  return waitFor(() => {
    const dropdown = mountedDropdown();
    if (!dropdown) {
      throw new Error("「可申请权限组」的下拉没有出现");
    }
    return dropdown;
  });
}

/**
 * 下拉里的某个权限组选项(选项以本地化组名作为 title)。
 *
 * 已选值读的是选项的 aria-selected 而不是控件里的标签: maxTagCount="responsive" 要靠
 * ResizeObserver 量宽度决定显示几个标签, jsdom 的 stub 从不回调, 标签会全被折叠掉。
 */
async function authorizationGroupOption(user: UserEvent, name: string): Promise<HTMLElement> {
  return within(await openAuthorizationGroups(user)).getByTitle(name);
}

async function selectedGroupNames(user: UserEvent): Promise<string[]> {
  const dropdown = await openAuthorizationGroups(user);
  return [...dropdown.querySelectorAll(".ant-select-item-option[aria-selected='true']")].map(
    (option) => option.getAttribute("title") ?? "",
  );
}

describe("RequestTargetPicker", () => {
  test("FF-10: 直接权限字段使用 group 语义并关联标题", () => {
    renderWithAntd(<RequestTargetPicker {...pickerProps()} />);

    const group = screen.getByRole("group", { name: "直接权限" });
    const labelledBy = group.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy as string)).toHaveTextContent("直接权限");
  });

  test("权限组多选下拉只展示本地化组名, 不带类别与 key", async () => {
    renderWithAntd(<RequestTargetPicker {...pickerProps({ authorizationGroups: CRM_GROUPS })} />);
    const user = userEvent.setup();

    const dropdown = await openAuthorizationGroups(user);
    expect(
      [...dropdown.querySelectorAll(".ant-select-item-option")].map((option) => option.getAttribute("title")),
    ).toEqual(["销售只读", "订单运营包"]);
  });

  test("未选应用时权限组下拉禁用且没有选项, 选定应用后选项才出现", async () => {
    // 目录按应用返回权限组: 没选应用时 authorizationGroups 本就是空的, 控件同时置灰。
    const { rerender } = renderWithAntd(
      <RequestTargetPicker {...pickerProps({ appKey: "", authorizationGroups: [] })} />,
    );
    const user = userEvent.setup();

    expect(authorizationGroupCombobox()).toBeDisabled();
    expect(screen.getByText("不选择权限组")).toBeVisible();
    expect(screen.getByText("请先选择应用后再选择权限组。")).toBeVisible();

    const selector = authorizationGroupCombobox().closest(".ant-select")?.querySelector(".ant-select-selector");
    await user.click(selector as HTMLElement);
    expect(mountedDropdown()).toBeNull();

    rerender(<RequestTargetPicker {...pickerProps({ appKey: "crm", authorizationGroups: CRM_GROUPS })} />);

    expect(authorizationGroupCombobox()).toBeEnabled();
    const dropdown = await openAuthorizationGroups(user);
    expect(
      [...dropdown.querySelectorAll(".ant-select-item-option")].map((option) => option.getAttribute("title")),
    ).toEqual(["销售只读", "订单运营包"]);
  });

  test("权限组多选按整套集合回传, 选中与取消都不丢掉其余已选组", async () => {
    const onChange = vi.fn();
    renderWithAntd(<StatefulGroupPicker initialGroupKeys={["sales-reader"]} onChange={onChange} />);
    const user = userEvent.setup();

    expect(await selectedGroupNames(user)).toEqual(["销售只读"]);

    await user.click(await authorizationGroupOption(user, "订单运营包"));
    expect(onChange).toHaveBeenLastCalledWith(["sales-reader", "order-ops"]);
    expect(await selectedGroupNames(user)).toEqual(["销售只读", "订单运营包"]);

    // 取消其中一个只摘掉这一个: 上一次选上的 order-ops 必须留着。
    await user.click(await authorizationGroupOption(user, "销售只读"));
    expect(onChange).toHaveBeenLastCalledWith(["order-ops"]);
    expect(await selectedGroupNames(user)).toEqual(["订单运营包"]);
  });

  test("撤销申请里基础授权之外的权限组不可选, 基础授权已有的组可取消也可选回来", async () => {
    const revokeBaseGrant: RevokeBaseGrantSnapshot = { groupKeys: ["sales-reader"], directSelectionKeys: [] };
    renderWithAntd(<StatefulGroupPicker initialGroupKeys={["sales-reader"]} revokeBaseGrant={revokeBaseGrant} />);
    const user = userEvent.setup();

    // 撤销目标是"撤销后保留下来的授权", 必须是基础授权的子集: 加进新权限组必被后端拒绝。
    const outOfSnapshot = await authorizationGroupOption(user, "订单运营包");
    expect(outOfSnapshot).toHaveClass("ant-select-item-option-disabled");
    await user.click(outOfSnapshot);
    expect(await selectedGroupNames(user)).toEqual(["销售只读"]);

    const baseGrantGroup = await authorizationGroupOption(user, "销售只读");
    expect(baseGrantGroup).not.toHaveClass("ant-select-item-option-disabled");

    await user.click(baseGrantGroup);
    expect(await selectedGroupNames(user)).toEqual([]);

    await user.click(baseGrantGroup);
    expect(await selectedGroupNames(user)).toEqual(["销售只读"]);
  });

  test("续期的只读态把权限组下拉整个禁用", async () => {
    renderWithAntd(
      <RequestTargetPicker
        {...pickerProps({ authorizationGroups: CRM_GROUPS, authorizationGroupKeys: ["sales-reader"], disabled: true })}
      />,
    );
    const user = userEvent.setup();

    expect(authorizationGroupCombobox()).toBeDisabled();
    expect(screen.getByText("已选 1 个权限组，可留空。")).toBeVisible();

    const selector = authorizationGroupCombobox().closest(".ant-select")?.querySelector(".ant-select-selector");
    await user.click(selector as HTMLElement);
    expect(mountedDropdown()).toBeNull();
  });

  test("应用下拉展示别名: 有别名拼成「别名 (技术名)」, 没别名只显示技术名", () => {
    renderWithAntd(
      <RequestTargetPicker
        {...pickerProps({
          apps: [
            { id: 1, app_key: "crm", name: "CRM", alias: "客户管理" },
            { id: 2, app_key: "billing", name: "Billing", alias: "" },
          ],
        })}
      />,
    );

    expect(screen.getByRole("option", { name: "客户管理 (CRM)" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Billing" })).toBeVisible();
  });
});
