import { describe, expect, test } from "vitest";

import { joinLabels } from "./joinLabels";

describe("joinLabels", () => {
  test("默认用顿号拼接, 空列表为短横线", () => {
    expect(joinLabels(["张三", "李四"])).toBe("张三、李四");
    expect(joinLabels([])).toBe("-");
    expect(joinLabels(undefined)).toBe("-");
    expect(joinLabels(["", null, "张三", undefined])).toBe("张三");
  });

  test("调用方可覆盖空值和分隔符", () => {
    expect(joinLabels(["a", "b"], { separator: ", " })).toBe("a, b");
    expect(joinLabels([], { empty: "—" })).toBe("—");
  });
});
