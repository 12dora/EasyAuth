import { describe, expect, test } from "vitest";

import type { PermissionGroupItem, PermissionItem } from "../../lib/domain";
import { collectPermissionKeys, filterGroupsByApp, isPermissionGroupItem } from "./permissionTree";

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

  test("isPermissionGroupItem 只识别权限组节点", () => {
    expect(isPermissionGroupItem(groups[0])).toBe(true);
    expect(isPermissionGroupItem(crmOrderRead)).toBe(false);
  });
});
