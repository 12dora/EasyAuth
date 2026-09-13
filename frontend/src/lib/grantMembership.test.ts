import { describe, expect, test } from "vitest";

import { formatGrantGroupNames } from "./grantMembership";
import type { Translator } from "./status";

const t: Translator = (key) => {
  if (key === "grant.customGroups") {
    return "自定义";
  }
  return String(key);
};

describe("formatGrantGroupNames", () => {
  test("没有权限组时显示自定义", () => {
    expect(formatGrantGroupNames([], t)).toBe("自定义");
  });

  test("只显示组名, 多个组用顿号连接", () => {
    expect(
      formatGrantGroupNames(
        [
          { key: "auditor", name: "审计员" },
          { key: "viewer", name: "只读" },
        ],
        t,
      ),
    ).toBe("审计员、只读");
  });

  test("目录行被删导致组名为空时退回展示 key", () => {
    expect(formatGrantGroupNames([{ key: "auditor", name: "" }], t)).toBe("auditor");
  });
});
