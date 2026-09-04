import { describe, expect, test } from "vitest";

import { parsePortalRequestList } from "./portalListPayload";

/** 与后端 `GET /portal/api/v1/me/access-requests` 的单条 item 逐字段对齐的最小载荷。 */
function requestRow(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    app_key: "crm",
    app_name: "CRM",
    app_alias: "",
    request_type: "grant",
    base_grant_id: null,
    base_grant_revision: null,
    status: "submitted",
    status_label: "等待审批",
    grant_type: "permanent",
    grant_expires_at: null,
    reason: "申请权限",
    submitted_at: "2026-07-01T10:00:00Z",
    authorization_groups: [],
    direct_grants: [],
    current_approvers: [],
    decided_by: "",
    decision_actor_type: "",
    decided_by_name: null,
    decided_at: null,
    decision_comment: "",
    approved_at: null,
    applied_at: null,
    withdrawn_at: null,
    ...overrides,
  };
}

function listPayload(row: Record<string, unknown>) {
  return { data: [row], pagination: { page: 1, page_size: 20, total_items: 1, total_pages: 1 } };
}

describe("parsePortalRequestList", () => {
  test("保留申请生命周期上的四个时刻", () => {
    const payload = parsePortalRequestList(
      listPayload(
        requestRow({
          status: "grant_applied",
          status_label: "已授权",
          decided_at: "2026-07-02T10:00:00Z",
          approved_at: "2026-07-02T10:00:00Z",
          applied_at: "2026-07-02T10:05:00Z",
        }),
      ),
    );

    expect(payload.data[0]).toMatchObject({
      decided_at: "2026-07-02T10:00:00Z",
      approved_at: "2026-07-02T10:00:00Z",
      applied_at: "2026-07-02T10:05:00Z",
      withdrawn_at: null,
    });
  });

  test.each(["approved_at", "applied_at", "withdrawn_at"])("缺少 %s 时明确报错", (field) => {
    const row: Record<string, unknown> = requestRow();
    delete row[field];

    expect(() => parsePortalRequestList(listPayload(row))).toThrow(
      `申请记录列表 data[0].${field} 必须是字符串或 null`,
    );
  });

  test.each(["approved_at", "applied_at", "withdrawn_at"])("%s 不是字符串或 null 时明确报错", (field) => {
    expect(() => parsePortalRequestList(listPayload(requestRow({ [field]: 1_700_000_000 })))).toThrow(
      `申请记录列表 data[0].${field} 必须是字符串或 null`,
    );
  });
});
