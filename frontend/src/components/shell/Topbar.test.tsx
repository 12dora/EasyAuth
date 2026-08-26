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

  test("门户双项用户菜单的方向键顺序与首尾循环正确", async () => {
    const user = userEvent.setup();
    renderTopbar({ mode: "portal", canAccessConsole: true });

    const trigger = screen.getByRole("button", { name: "当前登录用户菜单" });
    await user.click(trigger);

    const adminItem = await screen.findByRole("menuitem", { name: "管理后台" });
    const logoutItem = screen.getByRole("menuitem", { name: "退出登录" });
    await waitFor(() => expect(adminItem).toHaveFocus());

    await user.keyboard("{ArrowDown}");
    expect(logoutItem).toHaveFocus();
    // 末项继续向下回到首项, 首项向上回到末项。
    await user.keyboard("{ArrowDown}");
    expect(adminItem).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(logoutItem).toHaveFocus();

    await user.keyboard("{Home}");
    expect(adminItem).toHaveFocus();
    await user.keyboard("{End}");
    expect(logoutItem).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  test("门户无控制台准入时用户菜单只剩登出一项", async () => {
    const user = userEvent.setup();
    renderTopbar({ mode: "portal" });

    await user.click(screen.getByRole("button", { name: "当前登录用户菜单" }));

    const logoutItem = await screen.findByRole("menuitem", { name: "退出登录" });
    await waitFor(() => expect(logoutItem).toHaveFocus());
    expect(screen.queryByRole("menuitem", { name: "管理后台" })).not.toBeInTheDocument();
    // 单项菜单的上下键都停在自身, 不应把焦点丢出菜单。
    await user.keyboard("{ArrowDown}");
    expect(logoutItem).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(logoutItem).toHaveFocus();
  });

  test("控制台用户菜单不出现管理后台入口", async () => {
    const user = userEvent.setup();
    renderTopbar({ canAccessConsole: true });

    await user.click(screen.getByRole("button", { name: "当前登录用户菜单" }));

    await screen.findByRole("menuitem", { name: "安全设置" });
    expect(screen.queryByRole("menuitem", { name: "管理后台" })).not.toBeInTheDocument();
  });

  test("未实现通知事实源前不渲染通知入口", () => {
    renderTopbar();

    expect(screen.queryByRole("button", { name: "通知中心" })).not.toBeInTheDocument();
  });
});

function renderTopbar(
  options: { mode?: "console" | "portal"; canAccessConsole?: boolean } = {},
) {
  const { canAccessConsole, mode = "console" } = options;
  return render(
    <MemoryRouter>
      <I18nProvider>
        <Topbar
          brandLogoUrl="/assets/brand/jiefa_logo.webp"
          mode={mode}
          currentUser={{ id: "admin", displayName: "管理员", role: "EasyAuth Admins", canAccessConsole }}
        />
      </I18nProvider>
    </MemoryRouter>,
  );
}
