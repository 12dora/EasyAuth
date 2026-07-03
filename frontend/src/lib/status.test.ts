import { describe, expect, test } from "vitest";

import { MESSAGES } from "../i18n/messages";
import type { Locale, MessageKey } from "../i18n/messages";
import { accessRequestStatusLabel, badgeToneForAccessRequestStatus } from "./status";

function translatorFor(locale: Locale) {
  return (key: MessageKey) => MESSAGES[locale][key];
}

describe("accessRequestStatusLabel", () => {
  test("用中文业务文案区分审批通过和授权生效", () => {
    const t = translatorFor("zh-CN");
    expect(accessRequestStatusLabel(t, "approved")).toBe("已批准");
    expect(accessRequestStatusLabel(t, "grant_applied")).toBe("已授权");
    expect(accessRequestStatusLabel(t, "grant_failed")).toBe("授权失败");
  });

  test("英文语言下输出英文文案", () => {
    const t = translatorFor("en");
    expect(accessRequestStatusLabel(t, "approved")).toBe("Approved");
    expect(accessRequestStatusLabel(t, "grant_applied")).toBe("Granted");
  });
});

describe("badgeToneForAccessRequestStatus", () => {
  test("失败状态使用 signal, 生效状态使用 evergreen", () => {
    expect(badgeToneForAccessRequestStatus("grant_failed")).toBe("signal");
    expect(badgeToneForAccessRequestStatus("rejected")).toBe("signal");
    expect(badgeToneForAccessRequestStatus("grant_applied")).toBe("evergreen");
  });
});
