import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test } from "vitest";

import { Dialog } from "./Dialog";
import { ConfirmDialog } from "./ui/ConfirmDialog";

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

  test("禁止关闭时 Escape、遮罩和关闭按钮均不可关闭", async () => {
    const user = userEvent.setup();
    render(
      <Dialog title="不可关闭" closeDisabled onClose={() => undefined}>
        <input aria-label="字段" />
      </Dialog>,
    );

    const closeButton = screen.getByRole("button", { name: "关闭弹窗" });
    const overlayButton = screen.getByRole("button", { name: "关闭弹窗遮罩" });
    expect(closeButton).toBeDisabled();
    expect(overlayButton).toBeDisabled();

    await user.keyboard("{Escape}");
    await user.click(closeButton);
    await user.click(overlayButton);
    expect(screen.getByRole("dialog", { name: "不可关闭" })).toBeVisible();
  });
});

function NestedDialogHarness() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [closed, setClosed] = useState<string[]>([]);
  const record = (who: string) => setClosed((previous) => [...previous, who]);

  return (
    <>
      <Dialog title="设置" onClose={() => record("outer")} footer={<button type="button">保存设置</button>}>
        <button type="button" onClick={() => setConfirmOpen(true)}>
          全部禁止
        </button>
      </Dialog>
      {confirmOpen ? (
        <ConfirmDialog
          title="确认改为全部禁止"
          message="超限后连 P0 调用也会被拒绝。"
          confirmLabel="确认"
          onConfirm={() => setConfirmOpen(false)}
          onClose={() => {
            setConfirmOpen(false);
            record("confirm");
          }}
        />
      ) : null}
      <span data-testid="closed">{closed.join(",")}</span>
    </>
  );
}

describe("Dialog 弹窗套弹窗", () => {
  test("只有最上层接管 Tab, 焦点不会穿过遮罩落回外层表单", async () => {
    const user = userEvent.setup();
    render(<NestedDialogHarness />);

    await user.click(screen.getByRole("button", { name: "全部禁止" }));

    const confirm = screen.getByRole("dialog", { name: "确认改为全部禁止" });
    const confirmClose = within(confirm).getByRole("button", { name: "关闭弹窗" });
    const confirmSubmit = within(confirm).getByRole("button", { name: "确认" });
    const outerSave = screen.getByRole("button", { name: "保存设置" });

    // 从确认框的第一个可聚焦元素 Shift+Tab: 落回确认框自己的最后一个, 而不是外层的「保存设置」。
    confirmClose.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(confirmSubmit);
    expect(document.activeElement).not.toBe(outerSave);

    // 正向 Tab 同样只在确认框内循环。
    confirmSubmit.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(confirmClose);
  });

  test("一次 Escape 只关掉最上层的确认框, 外层弹窗留在原地", async () => {
    const user = userEvent.setup();
    render(<NestedDialogHarness />);

    await user.click(screen.getByRole("button", { name: "全部禁止" }));
    expect(screen.getByRole("dialog", { name: "确认改为全部禁止" })).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "确认改为全部禁止" })).not.toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "设置" })).toBeVisible();
    expect(screen.getByTestId("closed")).toHaveTextContent("confirm");

    // 确认框关掉之后, 外层重新成为栈顶, Escape 照常生效。
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByTestId("closed")).toHaveTextContent("confirm,outer");
  });
});
