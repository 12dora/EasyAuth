import { describe, expect, test } from "vitest";

import { isAccountKind } from "./person";

describe("isAccountKind", () => {
  test("接受 directory / local / unresolved, 其余值拒绝", () => {
    expect(isAccountKind("directory")).toBe(true);
    expect(isAccountKind("local")).toBe(true);
    expect(isAccountKind("unresolved")).toBe(true);
    expect(isAccountKind("")).toBe(false);
    expect(isAccountKind("admin")).toBe(false);
    expect(isAccountKind(undefined)).toBe(false);
  });
});
