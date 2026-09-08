import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { PermissionSelector } from "./PermissionSelector";

const SELF = { key: "SELF", name: "本人" };

function permission(index: number): ScopedPermissionItem {
  return { id: index, app_key: "crm", key: `crm.perm.${index}`, name: `权限 ${index}`, scopes: [SELF] } as ScopedPermissionItem;
}

function groupWith(permissionCount: number, key = "orders", offset = 0): ScopedPermissionGroupItem {
  return {
    id: offset + 1,
    app_key: "crm",
    type: "group",
    key,
    name: key,
    permissions: Array.from({ length: permissionCount }, (_, index) => permission(offset + index)),
  } as ScopedPermissionGroupItem;
}

function selector(permissionCount: number, expandedGroupKeys: string[]) {
  return selectorWithGroups([groupWith(permissionCount)], expandedGroupKeys);
}

function selectorWithGroups(groups: ScopedPermissionGroupItem[], expandedGroupKeys: string[]) {
  const noop = () => undefined;
  return (
    <PermissionSelector
      appKey="crm"
      groups={groups}
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

describe("PermissionSelector 前后两批过渡各自定案", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  test("先后收起两个大组: 第一批放完不会让第二批反悔重播退场动画", () => {
    vi.useFakeTimers();
    const groups = [groupWith(30, "a", 0), groupWith(30, "b", 100)];
    const { container, rerender } = render(selectorWithGroups(groups, ["a", "b"]));
    // 两个组的行都在场: 2 个组行 + 60 条权限。
    expect(container.querySelectorAll("tbody tr")).toHaveLength(62);

    // 第一批: 收起 a。30 行不到阈值, 照常播退场动画, 行留在 DOM 里等动画放完。
    rerender(selectorWithGroups(groups, ["b"]));
    expect(motionRowCount(container, "exiting")).toBe(30);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(62);

    act(() => {
      vi.advanceTimersByTime(80);
    });

    // 第二批: 收起 b。此刻还在播的 30 行 + 新的 30 行 = 60, 超阈值, 这一批直接摘掉。
    rerender(selectorWithGroups(groups, []));
    expect(motionRowCount(container, "exiting")).toBe(30);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(32);

    // 第一批的计时器到点: a 的行被摘掉。b 那一批的决定必须还是"跳过",
    // 否则它的 30 行会重新挂上、重播一遍退场动画, 再被 a 的计时器提前摘走。
    act(() => {
      vi.advanceTimersByTime(80);
    });
    expect(motionRowCount(container, "exiting")).toBe(0);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);

    // 第二批的计时器到点后同样只剩两个组行。
    act(() => {
      vi.advanceTimersByTime(120);
    });
    expect(motionRowCount(container, "exiting")).toBe(0);
    expect(container.querySelectorAll("tbody tr")).toHaveLength(2);
  });
});
