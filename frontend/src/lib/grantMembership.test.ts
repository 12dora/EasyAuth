import { describe, expect, test } from "vitest";

import { formatGrantGroupNames } from "./grantMembership";

describe("formatGrantGroupNames", () => {
  test("没有权限组时显示占位符", () => {
    expect(formatGrantGroupNames([])).toBe("-");
  });

  test("只显示组名, 多个组用顿号连接", () => {
    expect(formatGrantGroupNames([
      { key: "auditor", name: "审计员" },
      { key: "viewer", name: "只读" },
    ])).toBe("审计员、只读");
  });

  test("目录行被删导致组名为空时退回展示 key", () => {
    expect(formatGrantGroupNames([{ key: "auditor", name: "" }])).toBe("auditor");
  });
});
