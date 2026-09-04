import { describe, expect, it } from "vitest";

import { formatAppDisplayName } from "./appDisplayName";

describe("formatAppDisplayName", () => {
  it("有别名时按 别名 (技术名) 拼接", () => {
    expect(formatAppDisplayName({ name: "EasyCustoms", alias: "海关数据" })).toBe("海关数据 (EasyCustoms)");
  });

  it("无别名或别名为空白时只显示技术名", () => {
    expect(formatAppDisplayName({ name: "NetBird" })).toBe("NetBird");
    expect(formatAppDisplayName({ name: "NetBird", alias: "  " })).toBe("NetBird");
    expect(formatAppDisplayName({ name: "NetBird", alias: null })).toBe("NetBird");
  });
});
