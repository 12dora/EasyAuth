import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { SecretDialog } from "./SecretDialog";

describe("SecretDialog", () => {
  test("仅通过弹窗展示一次性明文凭据, 关闭后通知父组件清除状态", async () => {
    const onClose = vi.fn();

    render(
      <SecretDialog
        title="静态 token 已创建"
        primaryLabel="plaintext_token"
        primaryValue="eat_secret_once"
        onClose={onClose}
      />,
    );

    expect(screen.getByText("静态 token 已创建")).toBeInTheDocument();
    expect(screen.getByText("eat_secret_once")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "关闭" }));

    expect(onClose).toHaveBeenCalledOnce();
  });
});
