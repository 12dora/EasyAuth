import { describe, expect, test } from "vitest";

import {
  OperationContractError,
  parseAuditLogRow,
  parseNullablePersonRef,
  parseOperationApprover,
  parsePersonRef,
} from "./operations";

describe("parseOperationApprover", () => {
  test("要求 account_kind, 接受 unresolved", () => {
    expect(parseOperationApprover({ user_id: "u-1", name: "张主管", account_kind: "directory" })).toEqual({
      user_id: "u-1",
      name: "张主管",
      account_kind: "directory",
    });
    expect(
      parseOperationApprover({
        user_id: "missing",
        name: "",
        department: "",
        account_kind: "unresolved",
      }),
    ).toMatchObject({ account_kind: "unresolved" });
  });

  test("缺少 account_kind 立即失败", () => {
    expect(() => parseOperationApprover({ user_id: "u-1", name: "张主管" })).toThrow(OperationContractError);
    expect(() => parseOperationApprover({ user_id: "u-1", name: "张主管" })).toThrow(/account_kind/);
  });
});

const PERSON = {
  user_id: "admin-1",
  name: "李管理员",
  department: "捷发-信息部",
  account_kind: "directory",
} as const;

describe("parsePersonRef", () => {
  test("接受完整 PersonRef", () => {
    expect(parsePersonRef(PERSON)).toEqual(PERSON);
  });

  test("缺少任一字段立即失败", () => {
    const { department: _dropped, ...withoutDepartment } = PERSON;
    expect(() => parsePersonRef(withoutDepartment)).toThrow(/department/);
    expect(() => parsePersonRef({ ...PERSON, account_kind: "admin" })).toThrow(/account_kind/);
    expect(() => parsePersonRef(null)).toThrow(OperationContractError);
  });
});

describe("parseNullablePersonRef", () => {
  test("null 表示系统或未解析到 UserMirror", () => {
    expect(parseNullablePersonRef(null, "actor_person")).toBeNull();
  });

  test("非法对象立即失败, 不回落为 null", () => {
    expect(() => parseNullablePersonRef({ user_id: "admin-1" }, "actor_person")).toThrow(/actor_person/);
  });
});

describe("parseAuditLogRow", () => {
  test("要求 actor_person, 接受人员对象或 null", () => {
    expect(
      parseAuditLogRow({
        actor_type: "user",
        actor_id: "admin-1",
        event_type: "grant.approved",
        actor_person: PERSON,
      }).actor_person,
    ).toEqual(PERSON);
    expect(
      parseAuditLogRow({
        actor_type: "system",
        actor_id: "",
        event_type: "job.ran",
        actor_person: null,
      }).actor_person,
    ).toBeNull();
  });

  test("缺少 actor_person 立即失败", () => {
    expect(() =>
      parseAuditLogRow({
        actor_type: "user",
        actor_id: "admin-1",
        event_type: "grant.approved",
      }),
    ).toThrow(/actor_person/);
  });
});
