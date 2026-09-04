import { describe, expect, test } from "vitest";

import { parsePortalRequestCatalog } from "./requestCatalogContract";

function catalog(overrides: Record<string, unknown> = {}) {
  return {
    apps: [{ id: 1, app_key: "crm", name: "CRM", alias: "" }],
    approver_options: [{ user_id: "boss", name: "老板" }],
    authorization_groups: [
      {
        id: 11,
        app_key: "crm",
        key: "reader",
        kind: "role",
        name: "只读",
        grants: [{ permission_key: "customer.read", scope_key: "SELF" }],
      },
    ],
    permission_groups: [],
    ungrouped_permissions: [],
    ...overrides,
  };
}

function authorizationGroup(overrides: Record<string, unknown>) {
  return catalog({
    authorization_groups: [
      { id: 11, app_key: "crm", key: "reader", kind: "role", name: "只读", grants: [], ...overrides },
    ],
  });
}

describe("parsePortalRequestCatalog", () => {
  test("完整目录原样通过", () => {
    const parsed = parsePortalRequestCatalog(catalog());

    expect(parsed.authorization_groups?.[0].grants).toEqual([
      { permission_key: "customer.read", scope_key: "SELF" },
    ]);
  });

  test("权限组缺少 grants 时拒绝消费", () => {
    // 后端 request_catalog_data 永远下发 grants(没配置时是空数组)。缺了它会被前端当成
    // "这个权限组什么都不覆盖", 直接权限就会与权限组重复进载荷, 因此必须在契约层失败。
    const { grants: _grants, ...withoutGrants } = authorizationGroup({}).authorization_groups[0];

    expect(() => parsePortalRequestCatalog(catalog({ authorization_groups: [withoutGrants] }))).toThrow(
      "申请目录.authorization_groups[0].grants 必须为数组",
    );
  });

  test("权限组 grants 元素结构错误时拒绝消费", () => {
    expect(() =>
      parsePortalRequestCatalog(authorizationGroup({ grants: [{ permission_key: "", scope_key: "SELF" }] })),
    ).toThrow("申请目录.authorization_groups[0].grants[0].permission_key 必须为非空字符串");

    expect(() =>
      parsePortalRequestCatalog(authorizationGroup({ grants: [{ permission_key: "customer.read" }] })),
    ).toThrow("申请目录.authorization_groups[0].grants[0].scope_key 必须为非空字符串");
  });

  test("权限组 grants 为空数组是合法的", () => {
    expect(parsePortalRequestCatalog(authorizationGroup({ grants: [] })).authorization_groups?.[0].grants).toEqual([]);
  });
});
