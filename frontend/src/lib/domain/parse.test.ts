import { describe, expect, test } from "vitest";

import { PersonContractError } from "./person";
import {
  bindParse,
  isRecord,
  parseNullablePersonRef,
  parsePersonRef,
  requireArray,
  requireBoolean,
  requireEnum,
  requireInteger,
  requireNonEmptyString,
  requireNullableString,
  requireNumber,
  requireRecord,
  requireString,
  optionalString,
} from "./parse";

const PERSON = {
  user_id: "admin-1",
  name: "李管理员",
  department: "捷发-信息部",
  account_kind: "directory",
  avatar_url: "",
} as const;

describe("parse primitives", () => {
  test("requireString / requireRecord / requireArray 默认用路径拼「必须是」", () => {
    expect(requireString("ok", "name")).toBe("ok");
    expect(() => requireString(1, "name")).toThrow("name 必须是字符串");
    expect(() => requireRecord([], "row")).toThrow("row 必须是对象");
    expect(() => requireArray({}, "items")).toThrow("items 必须是数组");
  });

  test("optionalString 把缺省和 null 当成空串, 非字符串仍失败", () => {
    expect(optionalString(undefined, "dept")).toBe("");
    expect(optionalString(null, "dept")).toBe("");
    expect(optionalString("安环部", "dept")).toBe("安环部");
    expect(() => optionalString(1, "dept")).toThrow("dept 必须是字符串");
  });

  test("requireNullableString 只接受字符串或 null", () => {
    expect(requireNullableString(null, "expires_at")).toBeNull();
    expect(requireNullableString("t", "expires_at")).toBe("t");
    expect(() => requireNullableString(undefined, "expires_at")).toThrow("expires_at 必须是字符串或 null");
  });

  test("requireNumber / requireInteger / requireBoolean / requireEnum", () => {
    expect(requireNumber(1.5, "n")).toBe(1.5);
    expect(() => requireNumber(Number.NaN, "n")).toThrow("n 必须是数字");
    expect(requireInteger(2, "page", { minimum: 1 })).toBe(2);
    expect(() => requireInteger(0, "page", { minimum: 1 })).toThrow("page 必须是大于等于 1 的整数");
    expect(requireBoolean(false, "on")).toBe(false);
    expect(requireEnum("role", "kind", ["role", "bundle"] as const)).toBe("role");
    expect(() => requireEnum("other", "kind", ["role", "bundle"] as const)).toThrow("kind 必须是 role 或 bundle");
    expect(requireNonEmptyString("x", "key")).toBe("x");
    expect(() => requireNonEmptyString("", "key")).toThrow("key 必须是非空字符串");
  });

  test("fail 工厂换成领域错误, copula 可切「为」", () => {
    class DemoError extends Error {
      constructor(readonly field: string) {
        super(`demo: ${field}`);
      }
    }
    const p = bindParse({ fail: (path) => new DemoError(path) });
    expect(() => p.requireString(1, "name")).toThrow(DemoError);
    expect(() => requireString(1, "name", { copula: "为" })).toThrow("name 必须为字符串");
  });

  test("isRecord 拒绝 null 与数组", () => {
    expect(isRecord({ a: 1 })).toBe(true);
    expect(isRecord(null)).toBe(false);
    expect(isRecord([])).toBe(false);
  });
});

describe("parsePersonRef", () => {
  test("接受完整 PersonRef, 缺字段抛 PersonContractError", () => {
    expect(parsePersonRef(PERSON)).toEqual(PERSON);
    const { avatar_url: _dropped, ...withoutAvatar } = PERSON;
    expect(() => parsePersonRef(withoutAvatar)).toThrow(PersonContractError);
  });

  test("fail 把 PersonContractError 换成领域错误", () => {
    class DemoError extends Error {
      constructor(readonly field: string) {
        super(field);
      }
    }
    expect(() => parsePersonRef(null, "actor", { fail: (path) => new DemoError(path) })).toThrow(DemoError);
    expect(() => parsePersonRef(null, "actor", { fail: (path) => new DemoError(path) })).toThrow(/actor/);
  });

  test("parseNullablePersonRef: null 合法, undefinedThrows 时缺字段失败", () => {
    expect(parseNullablePersonRef(null, "actor")).toBeNull();
    expect(() => parseNullablePersonRef(undefined, "actor", { undefinedThrows: true })).toThrow(/actor/);
    expect(parseNullablePersonRef(PERSON, "actor")).toEqual(PERSON);
  });
});
