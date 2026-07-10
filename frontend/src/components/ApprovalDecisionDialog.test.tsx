import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { ApprovalDecisionDialog } from "./ApprovalDecisionDialog";

describe("ApprovalDecisionDialog", () => {
  test("详情未就绪时禁止提交", () => {
    render(
      <ApprovalDecisionDialog
        mode="approve"
        description="申请说明"
        details={<p>详情加载失败</p>}
        errorMessage=""
        isSubmitting={false}
        canSubmit={false}
        onClose={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect(screen.getByText("详情加载失败")).toBeVisible();
    expect(screen.getByRole("button", { name: "确认同意" })).toBeDisabled();
  });

  test("提交中禁止取消、遮罩、关闭按钮和 Escape 关闭", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <ApprovalDecisionDialog
        mode="approve"
        description="申请说明"
        errorMessage=""
        isSubmitting
        onClose={onClose}
        onSubmit={() => undefined}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "同意申请" });
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "关闭弹窗" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "关闭弹窗遮罩" })).toBeDisabled();

    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    expect(dialog).toBeVisible();
  });
});
