import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { PortalGrantRow } from "../portalListPayload";

import { AccessRequestFields } from "./AccessRequestFields";

function renderFields(overrides: Partial<Parameters<typeof AccessRequestFields>[0]> = {}) {
  render(
    <AccessRequestFields
      requestType="grant"
      appKey="crm"
      baseGrantId=""
      currentGrants={[]}
      approverOptions={[{ user_id: "boss", name: "老板" }]}
      selectedApproverUserIds={[]}
      grantType="timed"
      expiresAt=""
      expiresAtError={false}
      reason=""
      onRequestTypeChange={vi.fn()}
      onBaseGrantChange={vi.fn()}
      onApproverToggle={vi.fn()}
      onGrantTypeChange={vi.fn()}
      onExpiresAtChange={vi.fn()}
      onReasonChange={vi.fn()}
      {...overrides}
    />,
  );
}

describe("AccessRequestFields", () => {
  test("FF-5: 过期时间输入带 min 约束且过去值展示内联错误", () => {
    renderFields({ expiresAtError: true });

    const input = screen.getByLabelText("过期时间");
    expect(input).toHaveAttribute("type", "datetime-local");
    expect(input.getAttribute("min")).toBeTruthy();
    expect(screen.getByText("过期时间必须晚于当前时间。")).toBeVisible();
  });

  test("FF-10: 审批人字段用 group 语义并通过 aria-labelledby 关联标题", () => {
    renderFields();

    const group = screen.getByRole("group");
    const labelledBy = group.getAttribute("aria-labelledby");
    expect(labelledBy).toBeTruthy();
    expect(document.getElementById(labelledBy as string)).toHaveTextContent("审批人");
    expect(document.querySelector('label[for][id$="-label"]')).toBeNull();
  });

  test("基础授权下拉按统一展示名渲染, 只跟版本号, 不再重复 app_key", () => {
    renderFields({
      requestType: "change",
      currentGrants: [
        grantRow({ grant_id: 7, app_key: "crm", app_name: "CRM", app_alias: "客户管理", grant_revision: 3 }),
        grantRow({ grant_id: 8, app_key: "billing", app_name: "Billing", app_alias: "", grant_revision: 1 }),
      ],
    });

    expect(screen.getByRole("option", { name: "客户管理 (CRM) v3" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Billing v1" })).toBeVisible();
  });
});

function grantRow(overrides: Partial<PortalGrantRow>): PortalGrantRow {
  return {
    app_key: "crm",
    app_name: "CRM",
    app_alias: "",
    grant_id: 1,
    grant_revision: 1,
    groups: [],
    grants: [],
    grant_version: 1,
    catalog_version: 1,
    snapshot_version: "1.1",
    grant_type: "permanent",
    grant_expires_at: null,
    ...overrides,
  } as PortalGrantRow;
}
