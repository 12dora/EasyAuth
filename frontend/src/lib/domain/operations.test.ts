import { describe, expect, test } from "vitest";

import { OperationContractError, parseOperationApprover } from "./operations";

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
