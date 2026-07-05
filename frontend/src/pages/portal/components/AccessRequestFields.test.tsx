import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import { AccessRequestFields } from "./AccessRequestFields";

function renderFields(overrides: Partial<Parameters<typeof AccessRequestFields>[0]> = {}) {
  render(
    <AccessRequestFields
      appKey="crm"
      approverOptions={[{ user_id: "boss", name: "老板" }]}
      selectedApproverUserIds={[]}
      grantType="timed"
      expiresAt=""
      expiresAtError={false}
      reason=""
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
});
