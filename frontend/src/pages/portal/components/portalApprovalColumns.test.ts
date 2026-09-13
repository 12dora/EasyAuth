import { describe, expect, test, vi } from "vitest";

import type { Translator } from "../../../lib/status";

import {
  PENDING_APPROVALS_MIN_WIDTH,
  PROCESSED_APPROVALS_MIN_WIDTH,
  approvalColumns,
} from "./portalApprovalColumns";

const t = ((key: string) => key) as Translator;
const sort = {};

describe("approvalColumns", () => {
  test("已处理列宽与列序: 申请人、应用、状态、内容、期限、提交、处理、审批意见", () => {
    const columns = approvalColumns(t, "processed", sort, false, vi.fn());
    expect(columns.map((column) => column.key)).toEqual([
      "applicant",
      "app",
      "status",
      "content",
      "term",
      "submitted_at",
      "decided_at",
      "decision_comment",
    ]);
    expect(columns.find((column) => column.key === "applicant")?.width).toBe(200);
    expect(columns.find((column) => column.key === "app")?.width).toBe(200);
    expect(columns.find((column) => column.key === "status")?.width).toBe(110);
    expect(columns.find((column) => column.key === "content")?.width).toBeUndefined();
    expect(columns.find((column) => column.key === "term")?.width).toBe(170);
    expect(columns.find((column) => column.key === "submitted_at")?.width).toBe(170);
    expect(columns.find((column) => column.key === "decided_at")?.width).toBe(170);
    expect(columns.find((column) => column.key === "decision_comment")?.width).toBeUndefined();
    expect(columns.find((column) => column.key === "status")?.ellipsis).toBe(false);
    expect(PROCESSED_APPROVALS_MIN_WIDTH).toBe(1500);
  });

  test("待办列宽: 申请人、应用 200, 期限与提交 170, 内容与原因弹性, 无状态列", () => {
    const columns = approvalColumns(t, "pending", sort, false, vi.fn());
    expect(columns.map((column) => column.key)).toEqual([
      "applicant",
      "app",
      "content",
      "term",
      "submitted_at",
      "reason",
      "actions",
    ]);
    expect(columns.find((column) => column.key === "applicant")?.width).toBe(200);
    expect(columns.find((column) => column.key === "app")?.width).toBe(200);
    expect(columns.find((column) => column.key === "content")?.width).toBeUndefined();
    expect(columns.find((column) => column.key === "term")?.width).toBe(170);
    expect(columns.find((column) => column.key === "submitted_at")?.width).toBe(170);
    expect(columns.find((column) => column.key === "reason")?.width).toBeUndefined();
    expect(PENDING_APPROVALS_MIN_WIDTH).toBe(1400);
  });
});
