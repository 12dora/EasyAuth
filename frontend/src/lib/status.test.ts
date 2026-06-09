import { describe, expect, test } from "vitest";

import { accessRequestStatusLabel, badgeToneForAccessRequestStatus } from "./status";

describe("accessRequestStatusLabel", () => {
  test("用中文业务文案区分审批通过和授权生效", () => {
    expect(accessRequestStatusLabel("approved")).toBe("已批准");
    expect(accessRequestStatusLabel("grant_applied")).toBe("已授权");
    expect(accessRequestStatusLabel("grant_failed")).toBe("授权失败");
  });
});

describe("badgeToneForAccessRequestStatus", () => {
  test("失败状态使用危险色, 生效状态使用成功色", () => {
    expect(badgeToneForAccessRequestStatus("grant_failed")).toBe("danger");
    expect(badgeToneForAccessRequestStatus("rejected")).toBe("danger");
    expect(badgeToneForAccessRequestStatus("grant_applied")).toBe("success");
  });
});
