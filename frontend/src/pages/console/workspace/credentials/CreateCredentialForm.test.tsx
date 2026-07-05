import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { CreateCredentialForm } from "./CreateCredentialForm";

describe("CreateCredentialForm(FF-4)", () => {
  test("创建进行中时两个按钮均禁用", () => {
    render(<CreateCredentialForm isCreating onCreateCredential={vi.fn(async () => undefined)} />);

    expect(screen.getByRole("button", { name: /静态 token/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /OAuth client/ })).toBeDisabled();
  });

  test("创建进行中时点击不会再次触发创建(杜绝重复提交)", async () => {
    const onCreateCredential = vi.fn(async () => undefined);
    const user = userEvent.setup();
    const { rerender } = render(
      <CreateCredentialForm isCreating={false} onCreateCredential={onCreateCredential} />,
    );

    await user.type(screen.getByLabelText("凭据名称"), "主凭据");
    await user.click(screen.getByRole("button", { name: /静态 token/ }));
    expect(onCreateCredential).toHaveBeenCalledTimes(1);
    expect(onCreateCredential).toHaveBeenCalledWith("static-tokens", "主凭据");

    // 父级把 isCreating 置真后, 再次点击不产生第二次创建。
    rerender(<CreateCredentialForm isCreating onCreateCredential={onCreateCredential} />);
    await user.click(screen.getByRole("button", { name: /静态 token/ }));
    expect(onCreateCredential).toHaveBeenCalledTimes(1);
  });
});
