import { describe, expect, test } from "vitest";

import type { PermissionGroupItem, PermissionItem } from "../../lib/domain";
import { collectGroupPermissions, collectPermissionKeys, filterGroupsByApp, isPermissionGroupItem, permissionMatchesApp } from "./permissionTree";

const crmOrderRead: PermissionItem = { id: 101, app_key: "crm", key: "orders.read", name: "查看订单" };
const crmRefundApprove: PermissionItem = {
  id: 102,
  app_key: "crm",
  key: "orders.refund.approve",
  name: "审批退款",
};
const biReportView: PermissionItem = { id: 201, app_key: "bi", key: "reports.view", name: "查看报表" };
const sharedAuditView: PermissionItem = { id: 301, key: "audit.view", name: "查看审计" };

const groups: PermissionGroupItem[] = [
  {
    id: 1,
    app_key: "crm",
    type: "group",
    key: "orders",
    name: "订单",
    permissions: [crmOrderRead, biReportView],
    children: [
      {
        id: 2,
        app_key: "crm",
        type: "group",
        key: "orders.refund",
        name: "退款",
        permissions: [crmRefundApprove],
      },
      biReportView,
    ],
  },
  {
    id: 3,
    app_key: "bi",
    type: "group",
    key: "reports",
    name: "报表",
    permissions: [biReportView],
  },
  {
    id: 4,
    type: "group",
    key: "shared",
    name: "共享",
    permissions: [sharedAuditView, biReportView],
  },
];

describe("portal permission tree helpers", () => {
  test("filterGroupsByApp 递归保留匹配应用的子组和直接权限", () => {
    expect(filterGroupsByApp(groups, "crm")).toEqual([
      {
        ...groups[0],
        permissions: [crmOrderRead],
        children: [
          {
            id: 2,
            app_key: "crm",
            type: "group",
            key: "orders.refund",
            name: "退款",
            permissions: [crmRefundApprove],
            children: [],
          },
        ],
      },
      {
        ...groups[2],
        permissions: [sharedAuditView],
        children: [],
      },
    ]);
  });

  test("filterGroupsByApp 跨 app 过滤权限和权限组", () => {
    const filtered = filterGroupsByApp(groups, "bi");

    expect(filtered.map((group) => group.key)).toEqual(["reports", "shared"]);
    expect(filtered[0]?.permissions?.map((permission) => permission.key)).toEqual(["reports.view"]);
    expect(filtered[1]?.permissions?.map((permission) => permission.key)).toEqual(["audit.view", "reports.view"]);
  });

  test("filterGroupsByApp 空 app 返回空树", () => {
    expect(filterGroupsByApp(groups, "")).toEqual([]);
  });

  test("collectPermissionKeys 收集子组权限和未分组直接权限", () => {
    expect(collectPermissionKeys([groups[0]], [sharedAuditView])).toEqual([
      "orders.read",
      "reports.view",
      "orders.refund.approve",
      "audit.view",
    ]);
  });

  test("collectPermissionKeys 对 permissions 和 children 中重复的直接权限按 key 去重", () => {
    expect(
      collectPermissionKeys(
        [
          {
            id: 5,
            app_key: "crm",
            type: "group",
            key: "activity.log",
            name: "活动日志",
            permissions: [crmOrderRead],
            children: [crmOrderRead],
          },
        ],
        [],
      ),
    ).toEqual(["orders.read"]);
  });

  test("isPermissionGroupItem 只识别权限组节点", () => {
    expect(isPermissionGroupItem(groups[0])).toBe(true);
    expect(isPermissionGroupItem(crmOrderRead)).toBe(false);
  });

  test("PermissionGroup 只做目录展示，不进入可提交权限 key", () => {
    expect(collectPermissionKeys([groups[0]], [])).not.toContain("orders");
    expect(collectPermissionKeys([groups[0]], [])).not.toContain("orders.refund");
  });

  // FF-12: 应用作用域判定的唯一口径, 分组与未分组共用。
  test("permissionMatchesApp 保留应用无关权限并按 app_key 精确匹配", () => {
    expect(permissionMatchesApp({ app_key: "" }, "crm")).toBe(true);
    expect(permissionMatchesApp({}, "crm")).toBe(true);
    expect(permissionMatchesApp({ app_key: "crm" }, "crm")).toBe(true);
    expect(permissionMatchesApp({ app_key: "bi" }, "crm")).toBe(false);
    expect(permissionMatchesApp({ app_key: "bi" }, "")).toBe(true);
  });

  // FF-13: 环形分组图(A⊂B⊂A)不得导致无限递归。
  test("collectGroupPermissions 在环形分组图下仍能终止", () => {
    const appLess: PermissionItem = { id: 999, key: "shared.only", name: "共享权限" };
    const groupA: PermissionGroupItem = { id: 1, type: "group", key: "a", name: "A", permissions: [appLess], children: [] };
    const groupB: PermissionGroupItem = { id: 2, type: "group", key: "b", name: "B", permissions: [], children: [groupA] };
    groupA.children = [groupB];

    const keys = collectGroupPermissions(groupA).map((permission) => permission.key);
    expect(keys).toEqual(["shared.only"]);
  });
});
