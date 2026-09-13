import { describe, expect, test } from "vitest";

import type { Translator } from "../lib/status";
import { formatPeople, resolvePeople, userOptionName } from "./UserCombobox";

const t: Translator = (key) => (key === "user.localAccount" ? "本地用户" : String(key));

describe("formatPeople", () => {
  test("空列表展示占位符, 目录人员拼接姓名与部门, 本地账号次行不是 ID", () => {
    expect(formatPeople(undefined, t)).toBe("-");
    expect(formatPeople([], t)).toBe("-");
    expect(
      formatPeople(
        [
          { user_id: "u-1", name: "张三", department: "捷发-安环部", account_kind: "directory" },
          { user_id: "local-admin:admin", name: "紧急管理员", department: "", account_kind: "local" },
        ],
        t,
      ),
    ).toBe("张三 · 捷发-安环部、紧急管理员 · 本地用户");
  });

  test("姓名缺失时主行退回 user_id, 次行仍不展示 UUID", () => {
    const uuid = "72635468-58ca-4b3a-9c1e-aaaaaaaaaaaa";
    expect(formatPeople([{ user_id: uuid, name: "", department: "销售部", account_kind: "directory" }], t)).toBe(
      `${uuid} · 销售部`,
    );
    expect(
      formatPeople([{ user_id: uuid, name: "系统管理员", department: "", account_kind: "local" }], t),
    ).toBe("系统管理员 · 本地用户");
  });
});

describe("resolvePeople", () => {
  test("按 ID 顺序对齐已解析候选, 尚未解析的留下空姓名", () => {
    expect(resolvePeople(["u-2", "u-1"], [{ user_id: "u-1", name: "张三", department: "销售部" }])).toEqual([
      { user_id: "u-2", name: "" },
      { user_id: "u-1", name: "张三", department: "销售部" },
    ]);
    expect(userOptionName({ user_id: "u-2", name: "" })).toBe("u-2");
  });
});
