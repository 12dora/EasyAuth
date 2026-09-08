import { render } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { PermissionSelector } from "./PermissionSelector";

const SELF = { key: "SELF", name: "本人" };

function permission(index: number): ScopedPermissionItem {
  return { id: index, app_key: "crm", key: `crm.perm.${index}`, name: `权限 ${index}`, scopes: [SELF] } as ScopedPermissionItem;
}

function groupWith(permissionCount: number): ScopedPermissionGroupItem {
  return {
    id: 1,
    app_key: "crm",
    type: "group",
    key: "orders",
    name: "订单",
    permissions: Array.from({ length: permissionCount }, (_, index) => permission(index)),
  } as ScopedPermissionGroupItem;
}

function selector(permissionCount: number, expandedGroupKeys: string[]) {
  const noop = () => undefined;
  return (
    <PermissionSelector
      appKey="crm"
      groups={[groupWith(permissionCount)]}
      ungroupedPermissions={[]}
      selectedKeys={[]}
      expandedGroupKeys={expandedGroupKeys}
      loading={false}
      errorMessage=""
      onPermissionScopeChange={noop}
      onPermissionGroupScopeChange={noop}
      onSelectPermissionKeys={noop}
      onClearPermissionKeys={noop}
      onExpandGroups={noop}
      onCollapseGroups={noop}
      onToggleGroup={noop}
    />
  );
}

/** 先渲染折叠态, 再切到展开态: 过渡集合在渲染期同步推进, 这一次渲染里子行就带着进场标记。 */
function renderExpanded(permissionCount: number) {
  const view = render(selector(permissionCount, []));
  view.rerender(selector(permissionCount, ["orders"]));
  return view;
}

function motionRowCount(container: HTMLElement, direction: "entering" | "exiting"): number {
  return container.querySelectorAll(`.permission-selector__row--${direction}`).length;
}

describe("PermissionSelector 展开动画的规模上限", () => {
  test("小规模展开仍然逐行播放进场动画", () => {
    const { container } = renderExpanded(5);

    // 权限组自己 + 5 条权限; 进场的是新出现的那 5 条子行, 权限组行本来就在。
    expect(container.querySelectorAll("tbody tr")).toHaveLength(6);
    expect(motionRowCount(container, "entering")).toBe(5);
  });

  test("大目录展开整批跳过逐行动画, 行本身照常渲染", () => {
    const { container } = renderExpanded(60);

    expect(container.querySelectorAll("tbody tr")).toHaveLength(61);
    // 60 条子行同时动 grid 行高与单元格内边距, 浏览器要连着 160ms 每帧重排整张表; 超过阈值就整批不播。
    expect(motionRowCount(container, "entering")).toBe(0);
  });

  test("大目录收起立即摘掉子行, 不留下停留一个动画时长的退场行", () => {
    const { container, rerender } = renderExpanded(60);

    rerender(selector(60, []));

    expect(motionRowCount(container, "exiting")).toBe(0);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  test("小规模收起仍然保留退场行与退场动画", () => {
    const { container, rerender } = renderExpanded(5);

    rerender(selector(5, []));

    expect(container.querySelectorAll("tbody tr")).toHaveLength(6);
    expect(motionRowCount(container, "exiting")).toBe(5);
  });
});
