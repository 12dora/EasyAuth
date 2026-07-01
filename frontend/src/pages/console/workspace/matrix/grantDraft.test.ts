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
      description: "财务角色",
      requestable: true,
      is_active: true,
      grants: [
        { permission: "invoice.read", scope: "SELF", is_active: true },
        { permission: "invoice.export", scope: "TEAM", is_active: true },
      ],
    });
  });
});
