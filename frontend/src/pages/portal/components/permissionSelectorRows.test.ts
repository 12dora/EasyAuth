import { describe, expect, test } from "vitest";

import { directGrantSelectionKey } from "../hooks/accessRequestSelection";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import {
  buildPermissionRows,
  currentPageGroupKeysFromRows,
  currentPageSelectionKeysFromRows,
  filterRowsToSelected,
  groupScopeChipState,
  groupScopeSelectionState,
  groupSelectionState,
  permissionScopeChipState,
  type PermissionSelectorRow,
} from "./permissionSelectorRows";

const SELF = { key: "SELF", name: "本人" };
const MANAGED_USERS = { key: "MANAGED_USERS", name: "管理用户" };
const ALL = { key: "ALL", name: "全部" };

function permission(key: string, scopes = [SELF]): ScopedPermissionItem {
  return { id: key.length, app_key: "crm", key, name: key, scopes } as ScopedPermissionItem;
}

/** 订单组: 直接挂 orders.read(单范围), 子组 orders.refund 挂 orders.refund.approve(三级范围)。 */
function ordersGroup(): ScopedPermissionGroupItem {
  return {
    id: 1,
    app_key: "crm",
    type: "group",
    key: "orders",
    name: "订单",
    permissions: [permission("orders.read")],
    children: [
      {
        id: 2,
        app_key: "crm",
        type: "group",
        key: "orders.refund",
        name: "退款",
        permissions: [permission("orders.refund.approve", [SELF, MANAGED_USERS, ALL])],
      },
    ],
  } as ScopedPermissionGroupItem;
}

function rowContext(overrides: Partial<Parameters<typeof buildPermissionRows>[2]> = {}) {
  return {
    expandedGroupKeys: [],
    enteringGroupKeys: [],
    exitingGroupKeys: [],
    selectedKeys: [],
    ...overrides,
  };
}

function rowIds(rows: PermissionSelectorRow[]): string[] {
  return rows.map((row) => row.id);
}

describe("groupSelectionState", () => {
  test("按整棵子树的全部权限范围判断三态", () => {
    const group = ordersGroup();
    const allKeys = [
      directGrantSelectionKey("orders.read", "SELF"),
      directGrantSelectionKey("orders.refund.approve", "SELF"),
      directGrantSelectionKey("orders.refund.approve", "MANAGED_USERS"),
      directGrantSelectionKey("orders.refund.approve", "ALL"),
    ];

    expect(groupSelectionState(group, [])).toBe("unchecked");
    expect(groupSelectionState(group, [allKeys[0]])).toBe("indeterminate");
    expect(groupSelectionState(group, allKeys)).toBe("checked");
  });

  test("权限组没有任何权限范围时是未勾选", () => {
    const emptyGroup = { id: 9, app_key: "crm", type: "group", key: "empty", name: "空组" } as ScopedPermissionGroupItem;

    expect(groupSelectionState(emptyGroup, [])).toBe("unchecked");
  });
});

describe("groupScopeSelectionState", () => {
  test("展示态(直接勾选 ∪ 权限组覆盖)全勾时表头到全勾, 缺一项则半选", () => {
    const group = ordersGroup();
    const selectedKeys = [directGrantSelectionKey("orders.read", "SELF")];
    const coveredKeys = [directGrantSelectionKey("orders.refund.approve", "SELF")];

    expect(groupScopeSelectionState(group, "SELF", selectedKeys)).toBe("indeterminate");
    expect(groupScopeSelectionState(group, "SELF", [...selectedKeys, ...coveredKeys])).toBe("checked");
  });

  test("只选到更低的权限范围时上层范围是半选", () => {
    const group = ordersGroup();

    expect(
      groupScopeSelectionState(group, "ALL", [directGrantSelectionKey("orders.refund.approve", "SELF")]),
    ).toBe("indeterminate");
  });

  test("没有权限支持该范围时是未勾选", () => {
    const group = ordersGroup();

    expect(groupScopeSelectionState(group, "GLOBAL", [])).toBe("unchecked");
  });
});

/*
 * 撤销申请下 chip 能不能点, 判据是"这一下真正会产生的选择集合有没有跑出保留范围",
 * 不是被点的那一个范围键: 范围递增, 勾高位会连低位一起补齐; 而已勾上的 chip 点下去是清空。
 */
describe("权限范围 chip 的方向与撤销禁用", () => {
  const READ_SELF = directGrantSelectionKey("orders.read", "SELF");
  const APPROVE_SELF = directGrantSelectionKey("orders.refund.approve", "SELF");
  const APPROVE_MANAGED = directGrantSelectionKey("orders.refund.approve", "MANAGED_USERS");
  const APPROVE_ALL = directGrantSelectionKey("orders.refund.approve", "ALL");

  function approvePermission(): ScopedPermissionItem {
    return permission("orders.refund.approve", [SELF, MANAGED_USERS, ALL]);
  }

  test("被点的范围本身在保留范围内, 但它会带上的低位范围越界: 仍然禁用", () => {
    // 基础授权只有 ALL 这一档; 用户先取消了它, 再点回来会把 SELF 与 MANAGED_USERS 一起补进保留范围。
    const retainableKeySet = new Set([APPROVE_ALL]);

    const chip = permissionScopeChipState(approvePermission(), "ALL", [], retainableKeySet);

    expect(chip.checked).toBe(false);
    expect(chip.shouldSelect).toBe(true);
    expect(chip.disabled).toBe(true);
  });

  test("已勾上的权限范围点下去是取消: 撤销申请里照旧可点", () => {
    const retainableKeySet = new Set([APPROVE_ALL]);

    const chip = permissionScopeChipState(approvePermission(), "ALL", [APPROVE_ALL], retainableKeySet);

    expect(chip.checked).toBe(true);
    expect(chip.shouldSelect).toBe(false);
    expect(chip.disabled).toBe(false);
  });

  test("全勾的权限组表头 chip 点下去是清空整个范围: 撤销申请里可点", () => {
    const selectedKeys = [READ_SELF, APPROVE_ALL];
    const retainableKeySet = new Set(selectedKeys);

    const allChip = groupScopeChipState(ordersGroup(), "ALL", selectedKeys, retainableKeySet);

    expect(allChip.checked).toBe(true);
    expect(allChip.shouldSelect).toBe(false);
    expect(allChip.disabled).toBe(false);
  });

  test("半勾的权限组表头 chip 点下去是补齐: 会补进保留范围之外的档位时禁用", () => {
    const selectedKeys = [READ_SELF, APPROVE_ALL];
    const retainableKeySet = new Set(selectedKeys);

    const selfChip = groupScopeChipState(ordersGroup(), "SELF", selectedKeys, retainableKeySet);
    const managedChip = groupScopeChipState(ordersGroup(), "MANAGED_USERS", selectedKeys, retainableKeySet);

    expect(selfChip.mixed).toBe(true);
    expect(selfChip.shouldSelect).toBe(true);
    // 补齐会加上 orders.refund.approve 的 SELF 档, 它不在基础授权里。
    expect(selfChip.disabled).toBe(true);
    expect(managedChip.shouldSelect).toBe(true);
    expect(managedChip.disabled).toBe(true);
    expect([APPROVE_SELF, APPROVE_MANAGED].every((key) => !retainableKeySet.has(key))).toBe(true);
  });

  test("不是撤销申请时没有保留范围一说, chip 一律可点", () => {
    expect(permissionScopeChipState(approvePermission(), "ALL", [], null).disabled).toBe(false);
    expect(groupScopeChipState(ordersGroup(), "SELF", [], null).disabled).toBe(false);
  });
});

describe("buildPermissionRows", () => {
  test("未展开的权限组只出一行, 展开后带出直接权限与子组", () => {
    const rows = buildPermissionRows([ordersGroup()], [permission("dashboard.view")], rowContext());

    expect(rowIds(rows)).toEqual(["group:orders", "permission:dashboard.view"]);

    const expandedRows = buildPermissionRows([ordersGroup()], [], rowContext({ expandedGroupKeys: ["orders"] }));

    expect(rowIds(expandedRows)).toEqual(["group:orders", "permission:orders.read", "group:orders.refund"]);
  });

  test("退场中的权限组保留子行并把退场态传给整条祖先链", () => {
    const rows = buildPermissionRows([ordersGroup()], [], rowContext({ exitingGroupKeys: ["orders"] }));

    expect(rowIds(rows)).toEqual(["group:orders", "permission:orders.read", "group:orders.refund"]);
    expect(rows.filter((row) => row.isExiting).map((row) => row.id)).toEqual([
      "permission:orders.read",
      "group:orders.refund",
    ]);
  });

  test("祖先正在进场时不再渲染退场中的子组子行", () => {
    const rows = buildPermissionRows(
      [ordersGroup()],
      [],
      rowContext({
        expandedGroupKeys: ["orders"],
        enteringGroupKeys: ["orders"],
        exitingGroupKeys: ["orders.refund"],
      }),
    );

    expect(rowIds(rows)).toEqual(["group:orders", "permission:orders.read", "group:orders.refund"]);
  });

  test("勾选计数与勾选态按展示态计算", () => {
    const rows = buildPermissionRows(
      [ordersGroup()],
      [],
      rowContext({
        expandedGroupKeys: ["orders"],
        selectedKeys: [directGrantSelectionKey("orders.read", "SELF")],
      }),
    );
    const [groupRow, permissionRow] = rows;

    expect(groupRow.type === "group" && groupRow.selectedCount).toBe(1);
    expect(groupRow.type === "group" && groupRow.permissionCount).toBe(2);
    expect(groupRow.type === "group" && groupRow.selectionState).toBe("indeterminate");
    expect(permissionRow.type === "permission" && permissionRow.isSelected).toBe(true);
  });
});

describe("行集合派生", () => {
  test("仅看已选过滤掉未勾选的行, 保留有勾选的权限组", () => {
    const rows = buildPermissionRows(
      [ordersGroup()],
      [permission("dashboard.view", [{ key: "GLOBAL", name: "全局" }])],
      rowContext({
        expandedGroupKeys: ["orders"],
        selectedKeys: [directGrantSelectionKey("orders.read", "SELF")],
      }),
    );

    expect(rowIds(filterRowsToSelected(rows))).toEqual(["group:orders", "permission:orders.read"]);
  });

  test("当前渲染行的选择键覆盖权限组整棵子树, 可按范围收窄", () => {
    const rows = buildPermissionRows([ordersGroup()], [], rowContext()).map((row) => ({ original: row }));

    expect(currentPageSelectionKeysFromRows(rows)).toEqual([
      directGrantSelectionKey("orders.read", "SELF"),
      directGrantSelectionKey("orders.refund.approve", "SELF"),
      directGrantSelectionKey("orders.refund.approve", "MANAGED_USERS"),
      directGrantSelectionKey("orders.refund.approve", "ALL"),
    ]);
    expect(currentPageSelectionKeysFromRows(rows, "ALL")).toEqual([
      directGrantSelectionKey("orders.refund.approve", "ALL"),
    ]);
    expect(currentPageGroupKeysFromRows(rows)).toEqual(["orders"]);
  });
});
