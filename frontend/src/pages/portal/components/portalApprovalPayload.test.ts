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
  test("接受后端真实返回的完整待办行(26 个字段)", () => {
    // 这条断言就是契约本身: 后端加字段而校验器没跟上时, 这里第一时间红。
    expect(Object.keys(pendingApproval)).toHaveLength(26);

    const payload = parseRow({ ...pendingApproval });

    expect(payload.data[0].current_approvers).toEqual([{ user_id: "me", name: "我本人" }]);
    expect(payload.data[0].decision_actor_type).toBe("");
    expect(payload.data[0].decided_by_name).toBeNull();
  });

  // 线上 `GET /portal/api/v1/me/approvals` 审批人视角的原样返回(2026-09-07 抓取)。
  // 上一次后端加 approved_at / applied_at / withdrawn_at 时校验器没跟上,
  // 整表被判成非法载荷、重试后弹「审批列表加载失败」, 所以这里把真实报文原样钉住。
  test("接受线上原样返回的待办行", () => {
    const payload = parseRow({
      id: 2,
      app_key: "netbird",
      app_name: "NetBird",
      app_alias: "远程接入VPN",
      request_type: "change",
      base_grant_id: 1,
      base_grant_revision: 2,
      status: "submitted",
      status_label: "等待审批",
      grant_type: "permanent",
      grant_expires_at: null,
      reason: "权限更新",
      submitted_at: "2026-09-07T08:07:59.958803+00:00",
      authorization_groups: [
        {
          key: "vlan88-access",
          kind: "role",
          name: "内网应用（应用服务、DNS）",
          grants: [{ permission: "vpn.vlan88", permission_name: "访问内网应用", scope: "GLOBAL" }],
        },
      ],
      direct_grants: [{ permission: "vpn.vlan10", permission_name: "访问办公网 VLAN 10", scope: "GLOBAL" }],
      current_approvers: [{ user_id: "1294dde0-4c54-460f-9728-0f4f54b91414", name: "认证系统管理员" }],
      decided_by: "",
      decision_actor_type: "",
      decided_by_name: null,
      decided_at: null,
      decision_comment: "",
      approved_at: null,
      applied_at: null,
      withdrawn_at: null,
      applicant: {
        user_id: "72635468-58ca-4688-8bbd-bec3d8531be1",
        name: "胡玉琴A",
        email: "",
        department: "",
      },
      approver_user_ids: ["1294dde0-4c54-460f-9728-0f4f54b91414"],
    });

    expect(payload.data[0].id).toBe(2);
    expect(payload.data[0].approved_at).toBeNull();
    expect(payload.data[0].applied_at).toBeNull();
    expect(payload.data[0].withdrawn_at).toBeNull();
  });

  test("接受已生效行: 审批通过时间与授权生效时间都已下发", () => {
    const payload = parseRow(
      decidedApproval({
        status: "grant_applied",
        status_label: "授权已落库, 权限已生效",
        approved_at: "2026-07-02T09:00:00Z",
        applied_at: "2026-07-02T09:00:05Z",
      }),
    );

    expect(payload.data[0].approved_at).toBe("2026-07-02T09:00:00Z");
    expect(payload.data[0].applied_at).toBe("2026-07-02T09:00:05Z");
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
    { label: "缺少 approved_at", row: rowWithout("approved_at") },
    { label: "缺少 applied_at", row: rowWithout("applied_at") },
    { label: "缺少 withdrawn_at", row: rowWithout("withdrawn_at") },
    { label: "approved_at 不是时间串", row: { ...pendingApproval, approved_at: "2026-07-02" } },
    // 下面四条是后端 access_requests_status_field_shape 约束下不可能出现的组合,
    // 出现即说明契约漂移, 必须当成非法载荷而不是照单渲染。
    {
      label: "待审批行却带了审批通过时间",
      row: { ...pendingApproval, approved_at: "2026-07-02T09:00:00Z" },
    },
    {
      label: "已生效行缺授权生效时间",
      row: decidedApproval({ status: "grant_applied", status_label: "授权已落库, 权限已生效", applied_at: null }),
    },
    {
      label: "已通过行却带了授权生效时间",
      row: decidedApproval({ status: "approved", status_label: "已通过", applied_at: "2026-07-02T09:00:05Z" }),
    },
    {
      label: "已撤回行缺撤回时间",
      row: decidedApproval({
        status: "withdrawn",
        status_label: "已撤回",
        decided_by: "",
        decision_actor_type: "",
        decided_by_name: null,
        decided_at: null,
        decision_comment: "",
        withdrawn_at: null,
      }),
    },
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
