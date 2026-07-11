import { describe, expect, test } from "vitest";

import { buildAuthorizationGroupPayload, createGrantDraft } from "./grantDraft";

describe("grantDraft", () => {
  test("维护 permission 与 scope 组成的 grant 草稿", () => {
    const draft = createGrantDraft([
      { permission: "invoice.read", scope: "SELF", is_active: true },
    ]);

    draft.addGrant("invoice.export", "TEAM");
    draft.setGrantActive("invoice.read", "SELF", false);
    draft.removeGrant("invoice.export", "TEAM");

    expect(draft.grants()).toEqual([
      { permission: "invoice.read", scope: "SELF", is_active: false },
    ]);
  });

  test("构造授权组保存 payload 时保留 permission 和 scope", () => {
    const payload = buildAuthorizationGroupPayload({
      key: "accountant",
      kind: "role",
      name: "会计",
      description: "财务角色",
      requestable: true,
      is_active: true,
      grants: [
        { permission: "invoice.read", scope: "SELF", is_active: true },
        { permission: "invoice.export", scope: "TEAM", is_active: true },
      ],
    });

    expect(payload).toEqual({
      key: "accountant",
      kind: "role",
      name: "会计",
      name_en: "",
      description: "财务角色",
      description_en: "",
      requestable: true,
      is_active: true,
      grants: [
        { permission: "invoice.read", scope: "SELF", is_active: true },
        { permission: "invoice.export", scope: "TEAM", is_active: true },
      ],
    });
  });

  test("构造授权组保存 payload 时完整 round-trip 双语字段", () => {
    const payload = buildAuthorizationGroupPayload({
      key: "accountant",
      kind: "role",
      name: "会计",
      name_en: "Accountant",
      description: "财务角色",
      description_en: "Finance role",
      requestable: true,
      is_active: true,
      grants: [],
    });

    expect(payload.name_en).toBe("Accountant");
    expect(payload.description_en).toBe("Finance role");
  });

  test("构造授权组保存 payload 时保留管理范围策略字段", () => {
    const payload = buildAuthorizationGroupPayload({
      key: "manager",
      kind: "role",
      name: "主管",
      description: "管理范围角色",
      requestable: true,
      is_active: true,
      grants: [
        {
          permission: "order.read",
          scope: "MANAGED_USERS",
          is_active: true,
          managed_scope_policy: {
            mode: "override",
            resolver: "dingtalk_manager_chain",
            enabled: true,
          },
          effective_managed_scope_policy: {
            resolver: "dingtalk_manager_chain",
            source: "authorization_group_grant",
            inherited_from: null,
            health_status: "healthy",
          },
        },
        {
          permission: "invoice.read",
          scope: "SELF",
          is_active: true,
        },
      ],
    });

    expect(payload.grants).toEqual([
      {
        permission: "order.read",
        scope: "MANAGED_USERS",
        is_active: true,
        managed_scope_policy: {
          mode: "override",
          resolver: "dingtalk_manager_chain",
          enabled: true,
        },
      },
      {
        permission: "invoice.read",
        scope: "SELF",
        is_active: true,
      },
    ]);
  });

  test.each([
    { mode: "inherit", resolver: "", enabled: false },
    { mode: "override", resolver: "dingtalk_manager_chain", enabled: true },
    { mode: "easyauth_team", resolver: "easyauth_team", enabled: true },
    { mode: "union", resolver: "union", enabled: true },
    { mode: "disabled", resolver: "disabled", enabled: false },
  ])("读取后直接保存时无损保留 $resolver 策略", (managedScopePolicy) => {
    const payload = buildAuthorizationGroupPayload({
      key: "manager",
      kind: "role",
      name: "主管",
      description: "",
      requestable: true,
      is_active: true,
      grants: [
        {
          permission: "order.read",
          scope: "MANAGED_USERS",
          is_active: true,
          managed_scope_policy: managedScopePolicy,
        },
      ],
    });

    expect(payload.grants[0]?.managed_scope_policy).toEqual(managedScopePolicy);
  });
});
