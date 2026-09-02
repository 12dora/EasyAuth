import { describe, expect, test } from "vitest";

import { MESSAGES } from "../../i18n/messages";
import type { Locale, MessageKey } from "../../i18n/messages";
import type { AuthorizationGroupKind } from "../../lib/domain";
import { authorizationGroupKindLabel, formatAuthorizationGroupLabel } from "./authorizationGroupLabel";

function translatorFor(locale: Locale) {
  return (key: MessageKey) => MESSAGES[locale][key];
}

describe("authorizationGroupKindLabel", () => {
  test("翻译授权组类别, 与控制台文案一致", () => {
    const t = translatorFor("zh-CN");
    expect(authorizationGroupKindLabel("role", t)).toBe("角色");
    expect(authorizationGroupKindLabel("bundle", t)).toBe("权限包");
  });

  test("英文语言下输出英文类别", () => {
    const t = translatorFor("en");
    expect(authorizationGroupKindLabel("role", t)).toBe("Role");
    expect(authorizationGroupKindLabel("bundle", t)).toBe("Bundle");
  });

  test("未知类别直接抛错, 不渲染占位符", () => {
    const t = translatorFor("zh-CN");
    expect(() => authorizationGroupKindLabel("group" as AuthorizationGroupKind, t)).toThrow("未知的授权组类别：group");
  });
});

describe("formatAuthorizationGroupLabel", () => {
  test("标签用翻译后的类别, 不出现接口枚举字面量", () => {
    const label = formatAuthorizationGroupLabel(
      { key: "vlan88-access", kind: "role", name: "VLAN88 访问" },
      translatorFor("zh-CN"),
    );
    expect(label).toBe("VLAN88 访问 [角色]");
    expect(label).not.toContain("role");
  });

  test("name 为空时回退到 key", () => {
    expect(
      formatAuthorizationGroupLabel({ key: "order-ops", kind: "bundle", name: "" }, translatorFor("zh-CN")),
    ).toBe("order-ops [权限包]");
  });
});
