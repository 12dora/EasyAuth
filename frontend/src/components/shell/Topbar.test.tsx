import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { Topbar } from "./Topbar";

describe("Topbar", () => {
  test("语言菜单打开后可用方向键移动并用 Escape 回到触发按钮", async () => {
    const user = userEvent.setup();
    renderTopbar();

    const trigger = screen.getByRole("button", { name: "切换语言" });
    trigger.focus();
    await user.keyboard("{Enter}");

    const menu = screen.getByRole("menu");
    expect(trigger).toHaveAttribute("aria-controls", menu.id);
    const zhItem = await screen.findByRole("menuitemradio", { name: "中文" });
    await waitFor(() => expect(zhItem).toHaveFocus());

    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitemradio", { name: "English" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  test("用户菜单使用 menu 键盘模型", async () => {
    const user = userEvent.setup();
    renderTopbar();

    const trigger = screen.getByRole("button", { name: "当前登录用户菜单" });
    await user.click(trigger);

    const securityItem = await screen.findByRole("menuitem", { name: "安全设置" });
    await waitFor(() => expect(securityItem).toHaveFocus());
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("menuitem", { name: "退出登录" })).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  test("未实现通知事实源前不渲染通知入口", () => {
    renderTopbar();

    expect(screen.queryByRole("button", { name: "通知中心" })).not.toBeInTheDocument();
  });
});

function renderTopbar() {
  return render(
    <MemoryRouter>
      <I18nProvider>
        <Topbar
          brandLogoUrl="/assets/brand/jiefa_logo.webp"
          mode="console"
          currentUser={{ id: "admin", displayName: "管理员", role: "EasyAuth Admins" }}
        />
      </I18nProvider>
    </MemoryRouter>,
  );
}
