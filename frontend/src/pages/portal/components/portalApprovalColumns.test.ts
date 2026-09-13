import { describe, expect, test, vi } from "vitest";

import type { Translator } from "../../../lib/status";

import {
  PENDING_APPROVALS_MIN_WIDTH,
  PROCESSED_APPROVALS_MIN_WIDTH,
  approvalColumns,
} from "./portalApprovalColumns";
import { pendingApproval } from "./portalApprovalTesting";

const t = ((key: string) => key) as Translator;
const sort = {};

describe("approvalColumns", () => {
  test("已处理列宽与列序: 申请人、应用、类型、状态、内容、期限、提交、处理、审批意见", () => {
    const columns = approvalColumns(t, "processed", sort, false, vi.fn());
    expect(columns.map((column) => column.key)).toEqual([
      "applicant",
      "app",
      "request_type",
      "status",
      "content",
      "term",
      "submitted_at",
      "decided_at",
      "decision_comment",
    ]);
    expect(columns.find((column) => column.key === "applicant")?.width).toBe(200);
    expect(columns.find((column) => column.key === "app")?.width).toBe(200);
    expect(columns.find((column) => column.key === "request_type")?.width).toBe(90);
    expect(columns.find((column) => column.key === "request_type")?.sorter).toBeUndefined();
    expect(columns.find((column) => column.key === "status")?.width).toBe(110);
    expect(columns.find((column) => column.key === "content")?.width).toBeUndefined();
    expect(columns.find((column) => column.key === "term")?.width).toBe(170);
    expect(columns.find((column) => column.key === "submitted_at")?.width).toBe(170);
    expect(columns.find((column) => column.key === "decided_at")?.width).toBe(170);
    expect(columns.find((column) => column.key === "decision_comment")?.width).toBeUndefined();
    expect(columns.find((column) => column.key === "status")?.ellipsis).toBe(false);
    expect(PROCESSED_APPROVALS_MIN_WIDTH).toBe(1500);
  });

  test("待办列宽: 申请人、应用 200, 类型 90 不可排序, 期限与提交 170, 内容与原因弹性, 无状态列", () => {
    const columns = approvalColumns(t, "pending", sort, false, vi.fn());
    expect(columns.map((column) => column.key)).toEqual([
      "applicant",
      "app",
      "request_type",
      "content",
      "term",
      "submitted_at",
      "reason",
      "actions",
    ]);
    expect(columns.find((column) => column.key === "applicant")?.width).toBe(200);
    expect(columns.find((column) => column.key === "app")?.width).toBe(200);
    expect(columns.find((column) => column.key === "request_type")?.width).toBe(90);
    expect(columns.find((column) => column.key === "request_type")?.sorter).toBeUndefined();
    expect(columns.find((column) => column.key === "content")?.width).toBeUndefined();
    expect(columns.find((column) => column.key === "term")?.width).toBe(170);
    expect(columns.find((column) => column.key === "submitted_at")?.width).toBe(170);
    expect(columns.find((column) => column.key === "reason")?.width).toBeUndefined();
    expect(PENDING_APPROVALS_MIN_WIDTH).toBe(1400);
  });

  test("类型列用 requestTypeLabel 渲染四种取值, 全量撤销内容格走 fullRevoke 文案", () => {
    const columns = approvalColumns(t, "pending", sort, false, vi.fn());
    const typeColumn = columns.find((column) => column.key === "request_type");
    const contentColumn = columns.find((column) => column.key === "content");
    const renderType = typeColumn?.render as (value: unknown, row: typeof pendingApproval) => string;
    const renderContent = contentColumn?.render as (value: unknown, row: typeof pendingApproval) => unknown;

    expect(renderType(undefined, { ...pendingApproval, request_type: "grant" })).toBe("portal.approvals.requestType.grant");
    expect(renderType(undefined, { ...pendingApproval, request_type: "change" })).toBe("portal.approvals.requestType.change");
    expect(renderType(undefined, { ...pendingApproval, request_type: "revoke" })).toBe("portal.approvals.requestType.revoke");
    expect(renderType(undefined, { ...pendingApproval, request_type: "renew" })).toBe("portal.approvals.requestType.renew");

    const fullRevoke = {
      ...pendingApproval,
      request_type: "revoke",
      authorization_groups: [],
      direct_grants: [],
    };
    const node = renderContent(undefined, fullRevoke) as { props: { children: string } };
    expect(node.props.children).toBe("portal.approvals.fullRevoke");
  });
});
