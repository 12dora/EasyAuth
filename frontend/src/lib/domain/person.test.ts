import { describe, expect, test } from "vitest";

import { isAccountKind, PersonContractError, readPersonRef } from "./person";

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

const PERSON = {
  user_id: "admin-1",
  name: "李管理员",
  department: "捷发-信息部",
  account_kind: "directory",
  avatar_url: "https://cdn.example.com/admin-1.png",
} as const;

describe("readPersonRef", () => {
  test("接受完整 PersonRef, 含空头像", () => {
    expect(readPersonRef(PERSON)).toEqual(PERSON);
    expect(readPersonRef({ ...PERSON, avatar_url: "" })).toEqual({ ...PERSON, avatar_url: "" });
  });

  test("缺少 avatar_url 或非字符串立即失败", () => {
    const { avatar_url: _dropped, ...withoutAvatar } = PERSON;
    expect(() => readPersonRef(withoutAvatar)).toThrow(PersonContractError);
    expect(() => readPersonRef(withoutAvatar)).toThrow(/avatar_url/);
    expect(() => readPersonRef({ ...PERSON, avatar_url: null })).toThrow(/avatar_url/);
  });
});
