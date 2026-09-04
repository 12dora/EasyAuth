import { describe, expect, test } from "vitest";

import { parseApprovalDetailPayload, parseApprovalListPayload } from "./portalApprovalPayload";
import { decidedApproval, pendingApproval } from "./portalApprovalTesting";

const INVALID_PAYLOAD_MESSAGE = "审批列表加载失败";

function listPayload(row: Record<string, unknown>) {
  return {
    data: [row],
    pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 },
  };
}

function parseRow(row: Record<string, unknown>) {
  return parseApprovalListPayload(listPayload(row), INVALID_PAYLOAD_MESSAGE);
}

describe("parseApprovalListPayload", () => {
  test("接受后端真实返回的完整待办行(23 个字段)", () => {
    // 这条断言就是契约本身: 后端加字段而校验器没跟上时, 这里第一时间红。
    expect(Object.keys(pendingApproval)).toHaveLength(23);

    const payload = parseRow({ ...pendingApproval });

    expect(payload.data[0].current_approvers).toEqual([{ user_id: "me", name: "我本人" }]);
    expect(payload.data[0].decision_actor_type).toBe("");
    expect(payload.data[0].decided_by_name).toBeNull();
  });

  test("接受已决行: current_approvers 为空且决定人三件套已填", () => {
    const payload = parseRow(
      decidedApproval({ status: "grant_applied", status_label: "授权已落库, 权限已生效" }),
    );

    expect(payload.data[0].current_approvers).toEqual([]);
    expect(payload.data[0].decision_actor_type).toBe("user");
    expect(payload.data[0].decided_by_name).toBe("我本人");
  });

  test("接受已撤回行: 申请人先撤回, 审批人打开详情时后端仍会返回 withdrawn", () => {
    const payload = parseRow(
      decidedApproval({
        status: "withdrawn",
        status_label: "已撤回",
        decided_by: "",
        decision_actor_type: "",
        decided_by_name: null,
        decided_at: null,
        decision_comment: "",
      }),
    );

    expect(payload.data[0].status).toBe("withdrawn");
  });

  test("接受 console_admin 决定的行", () => {
    const payload = parseRow(
      decidedApproval({ status: "rejected", status_label: "已拒绝", decision_actor_type: "console_admin" }),
    );

    expect(payload.data[0].decision_actor_type).toBe("console_admin");
  });

  test.each([
    { label: "多出未知字段", row: { ...pendingApproval, unexpected: true } },
    { label: "缺少 app_alias", row: rowWithout("app_alias") },
    { label: "app_alias 不是字符串", row: { ...pendingApproval, app_alias: null } },
    { label: "缺少 current_approvers", row: rowWithout("current_approvers") },
    { label: "缺少 decision_actor_type", row: rowWithout("decision_actor_type") },
    { label: "缺少 decided_by_name", row: rowWithout("decided_by_name") },
    { label: "current_approvers 不是数组", row: { ...pendingApproval, current_approvers: {} } },
    {
      label: "current_approvers 元素多出字段",
      row: { ...pendingApproval, current_approvers: [{ user_id: "me", name: "我本人", email: "me@example.test" }] },
    },
    {
      label: "current_approvers 元素缺 name",
      row: { ...pendingApproval, current_approvers: [{ user_id: "me" }] },
    },
    {
      label: "current_approvers.user_id 为空串",
      row: { ...pendingApproval, current_approvers: [{ user_id: "  ", name: "我本人" }] },
    },
    {
      label: "current_approvers.name 不是字符串",
      row: { ...pendingApproval, current_approvers: [{ user_id: "me", name: null }] },
    },
    { label: "decision_actor_type 取值不在枚举内", row: { ...pendingApproval, decision_actor_type: "robot" } },
    { label: "decision_actor_type 不是字符串", row: { ...pendingApproval, decision_actor_type: null } },
    { label: "decided_by_name 不是字符串也不是 null", row: { ...pendingApproval, decided_by_name: 7 } },
  ])("拒绝与后端契约不一致的行: $label", ({ row }) => {
    expect(() => parseRow(row)).toThrow(INVALID_PAYLOAD_MESSAGE);
  });
});

describe("parseApprovalDetailPayload", () => {
  test("接受后端真实返回的完整详情行", () => {
    const { approval } = parseApprovalDetailPayload(
      { approval: { ...pendingApproval } },
      INVALID_PAYLOAD_MESSAGE,
      pendingApproval.id,
    );

    expect(approval.current_approvers).toEqual([{ user_id: "me", name: "我本人" }]);
  });

  test("详情行多出未知字段时同样拒绝", () => {
    expect(() =>
      parseApprovalDetailPayload(
        { approval: { ...pendingApproval, unexpected: true } },
        INVALID_PAYLOAD_MESSAGE,
        pendingApproval.id,
      ),
    ).toThrow(INVALID_PAYLOAD_MESSAGE);
  });
});

function rowWithout(key: string): Record<string, unknown> {
  const row: Record<string, unknown> = { ...pendingApproval };
  delete row[key];
  return row;
}
