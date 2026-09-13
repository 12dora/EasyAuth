import { describe, expect, test } from "vitest";

import { ApprovalInstanceContractError, parseApprovalInstanceRow } from "./approval";

const INSTANCE = {
  instance_id: "ai-1",
  app_key: "crm",
  app_name: "CRM",
  app_alias: "客户管理",
  template_key: "leave",
  biz_key: "REQ-1",
  status: "approved",
  originator_user_id: "emp-1",
  originator_name: "胡玉琴",
  originator_department: "捷发-安环部",
  originator_account_kind: "directory",
  dingtalk_process_instance_id: "PROC-1",
  delivery_state: "delivered",
  delivery_attempts: 1,
  delivery_last_error: "",
  last_error: "",
  created_at: "2026-07-01T09:00:00Z",
  completed_at: "2026-07-01T10:00:00Z",
};

describe("parseApprovalInstanceRow", () => {
  test("要求 originator_account_kind, 接受 unresolved", () => {
    expect(parseApprovalInstanceRow(INSTANCE).originator_account_kind).toBe("directory");
    expect(
      parseApprovalInstanceRow({ ...INSTANCE, originator_account_kind: "unresolved", originator_name: "" })
        .originator_account_kind,
    ).toBe("unresolved");
  });

  test("缺少 originator_account_kind 立即失败", () => {
    const { originator_account_kind: _omitted, ...missing } = INSTANCE;
    expect(() => parseApprovalInstanceRow(missing)).toThrow(ApprovalInstanceContractError);
    expect(() => parseApprovalInstanceRow(missing)).toThrow(/originator_account_kind/);
  });
});
