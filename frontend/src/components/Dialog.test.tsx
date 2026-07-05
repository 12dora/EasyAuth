import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test } from "vitest";

import { Dialog } from "./Dialog";

function DialogHarness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        打开弹窗
      </button>
      {open ? (
        <Dialog title="标题" onClose={() => setOpen(false)} footer={<button type="button">确定</button>}>
          <input aria-label="字段" />
        </Dialog>
      ) : null}
    </>
  );
}

describe("Dialog 焦点陷阱(FF-6)", () => {
  test("打开时焦点移入面板, Tab 在面板内循环, 关闭后焦点归还触发按钮", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);

    const trigger = screen.getByRole("button", { name: "打开弹窗" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog");
    expect(dialog.contains(document.activeElement)).toBe(true);

    const closeButton = screen.getByRole("button", { name: "关闭弹窗" });
    const confirmButton = screen.getByRole("button", { name: "确定" });

    // 从最后一个可聚焦元素 Tab -> 回到第一个。
    confirmButton.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(closeButton);

    // 从第一个 Shift+Tab -> 跳到最后一个。
    closeButton.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirmButton);

    // Escape 关闭后焦点归还给打开弹窗前聚焦的触发按钮。
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
