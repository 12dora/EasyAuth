import { describe, expect, test } from "vitest";

import {
  HandoverContractError,
  parseHandoverDeferRecord,
  parseHandoverPersonRef,
  parseHandoverTaskPersonContract,
  parseNullableHandoverPersonRef,
} from "./handover";

const directoryPerson = {
  user_id: "u-1",
  name: "张三",
  department: "捷发-安环部",
  account_kind: "directory",
} as const;

describe("parseHandoverPersonRef", () => {
  test("接受完整 PersonRef", () => {
    expect(parseHandoverPersonRef(directoryPerson)).toEqual(directoryPerson);
  });

  test("缺少 account_kind 或非法值立即失败", () => {
    expect(() => parseHandoverPersonRef({ user_id: "u-1", name: "张三", department: "" })).toThrow(HandoverContractError);
    expect(() => parseHandoverPersonRef({ ...directoryPerson, account_kind: "admin" })).toThrow(/account_kind/);
  });

  test("department 必须是字符串", () => {
    expect(() => parseHandoverPersonRef({ user_id: "u-1", name: "张三", account_kind: "directory" })).toThrow(
      /department/,
    );
  });
});

describe("parseNullableHandoverPersonRef", () => {
  test("null 合法, 字段缺失立即失败", () => {
    expect(parseNullableHandoverPersonRef(null, "created_by_person")).toBeNull();
    expect(() => parseNullableHandoverPersonRef(undefined as never, "created_by_person")).toThrow(/created_by_person/);
  });
});

describe("parseHandoverDeferRecord", () => {
  test("要求 actor_person, 允许 null", () => {
    expect(
      parseHandoverDeferRecord({
        escalation_level: 0,
        actor_id: "su-1",
        actor_person: null,
        at: "2026-08-01T00:00:00Z",
        reason: "业务高峰",
      }),
    ).toMatchObject({ actor_id: "su-1", actor_person: null });
    expect(
      parseHandoverDeferRecord({
        escalation_level: 0,
        actor_id: "u-1",
        actor_person: directoryPerson,
        at: "2026-08-01T00:00:00Z",
        reason: "业务高峰",
      }).actor_person,
    ).toEqual(directoryPerson);
  });

  test("缺少 actor_person 立即失败", () => {
    expect(() =>
      parseHandoverDeferRecord({
        escalation_level: 0,
        actor_id: "su-1",
        at: "2026-08-01T00:00:00Z",
        reason: "业务高峰",
      }),
    ).toThrow(/actor_person/);
  });
});

describe("parseHandoverTaskPersonContract", () => {
  test("校验 created_by_person 与 defer_history[].actor_person", () => {
    expect(
      parseHandoverTaskPersonContract({
        created_by: "u-1",
        created_by_person: directoryPerson,
        escalation: {
          defer_history: [
            {
              escalation_level: 0,
              actor_id: "su-1",
              actor_person: null,
              at: "2026-08-01T00:00:00Z",
              reason: "顺延",
            },
          ],
        },
      }),
    ).toEqual({
      created_by_person: directoryPerson,
      defer_history: [
        {
          escalation_level: 0,
          actor_id: "su-1",
          actor_person: null,
          at: "2026-08-01T00:00:00Z",
          reason: "顺延",
        },
      ],
    });
  });

  test("created_by_person 缺失立即失败, null 合法", () => {
    expect(() => parseHandoverTaskPersonContract({ escalation: { defer_history: [] } })).toThrow(/created_by_person/);
    expect(parseHandoverTaskPersonContract({ created_by_person: null, escalation: { defer_history: [] } })).toEqual({
      created_by_person: null,
      defer_history: [],
    });
  });
});
