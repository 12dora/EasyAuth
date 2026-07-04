import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { App } from "../App";
import { I18nProvider } from "../i18n/I18nProvider";
import { AppShell } from "./AppShell";

const layoutShellCss = readFileSync(resolve(__dirname, "../styles/layout-shell.css"), "utf8");
const responsiveCss = readFileSync(resolve(__dirname, "../styles/responsive.css"), "utf8");

function renderShell(
  mode: "console" | "portal" = "console",
  currentUserId = "",
  initialEntry?: string,
) {
  const currentUser = {
    avatarUrl: "https://authentik.example.test/media/avatars/alice.png",
    displayName: mode === "console" ? "控制台用户" : "张三",
    id: currentUserId,
    logoutUrl: "/auth/logout/",
    role: mode === "console" ? "EasyAuth Admins" : "研发中心",
  };

  render(
    <I18nProvider>
      <MemoryRouter initialEntries={[initialEntry ?? (mode === "console" ? "/console" : "/portal")]}>
        <Routes>
          <Route element={<AppShell currentUser={currentUser} currentUserId={currentUserId} mode={mode} />}>
            <Route path={mode === "console" ? "/console" : "/portal"} element={<div>页面内容</div>} />
            <Route path={mode === "console" ? "/console/settings" : "/portal/settings"} element={<div>设置页面</div>} />
            <Route path={mode === "console" ? "/console/operations/access-requests" : "/portal/request"} element={<div>申请页面</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("AppShell", () => {
  test("控制台壳层展示 EasyTrade 风格的顶栏、工具区和侧边导航", () => {
    renderShell("console");

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByLabelText("EasyAuth 管理控制台")).toBeVisible();
    expect(screen.getByRole("img", { name: "EasyAuth" })).toBeVisible();
    expect(screen.getByRole("button", { name: "切换语言" })).toBeVisible();
    expect(screen.getByRole("button", { name: "通知中心" })).toBeVisible();
    expect(screen.getByText("控制台用户")).toBeVisible();
    expect(screen.getByText("EasyAuth Admins")).toBeVisible();
    expect(screen.getByRole("img", { name: "控制台用户头像" })).toHaveAttribute(
      "src",
      "https://authentik.example.test/media/avatars/alice.png",
    );
    expect(screen.getByText("概览")).toBeVisible();
    expect(screen.getByText("运营")).toBeVisible();
    expect(within(screen.getByRole("navigation", { name: "主导航" })).getByText("应用")).toBeVisible();
  });

  test("员工门户壳层展示当前用户标识和门户身份", () => {
    renderShell("portal", "alice@example.com");

    expect(screen.getByLabelText("EasyAuth 员工门户")).toBeVisible();
    expect(screen.getByText("张三")).toBeVisible();
    expect(screen.getByText("研发中心")).toBeVisible();
    expect(screen.queryByText("系统管理员")).not.toBeInTheDocument();
    expect(screen.queryByText("alice@example.com")).not.toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "主导航" })).getByText("我的权限")).toBeVisible();
  });

  test("缺少友好展示名时不会把 authentik subject 显示在顶栏", () => {
    render(
      <MemoryRouter initialEntries={["/portal"]}>
        <Routes>
          <Route
            element={
              <AppShell
                currentUser={{
                  id: "dingmockcorp000000000000000000000000:100000000000000001",
                  logoutUrl: "/auth/logout/",
                }}
                mode="portal"
              />
            }
          >
            <Route path="/portal" element={<div>页面内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByText("当前用户")).toBeVisible();
    expect(screen.queryByText("dingmockcorp000000000000000000000000:100000000000000001")).not.toBeInTheDocument();
  });

  test("无当前用户时仍展示共享顶栏但隐藏用户身份区域", () => {
    render(
      <MemoryRouter initialEntries={["/auth/logged-out/"]}>
        <Routes>
          <Route element={<AppShell mode="portal" />}>
            <Route path="/auth/logged-out/" element={<div>已登出页面</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByLabelText("EasyAuth 统一权限中心")).toBeVisible();
    expect(screen.getByText("统一权限中心")).toBeVisible();
    expect(screen.queryByText("员工门户")).not.toBeInTheDocument();
    expect(screen.getByText("已登出页面")).toBeVisible();
    expect(screen.queryByRole("button", { name: "当前登录用户菜单" })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /头像/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "退出登录" })).not.toBeInTheDocument();
  });

  test("登出页复用共享顶栏并忽略已传入的当前用户", () => {
    render(
      <MemoryRouter initialEntries={["/auth/logged-out/?next=/portal/requests"]}>
        <App
          currentUser={{
            avatarUrl: "https://authentik.example.test/media/avatars/alice.png",
            displayName: "张三",
            id: "alice@example.com",
            logoutUrl: "/auth/logout/",
            role: "研发中心",
          }}
          shell="portal"
        />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText("EasyAuth 统一权限中心")).toBeVisible();
    expect(screen.getByText("统一权限中心")).toBeVisible();
    expect(screen.queryByText("员工门户")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "已登出" })).toBeVisible();
    expect(screen.getByRole("link", { name: "重新登录" })).toHaveAttribute("href", "/auth/local/");
    expect(screen.queryByText("张三")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "张三头像" })).not.toBeInTheDocument();
  });

  test("登出页登录按钮固定指向登录页且忽略外部 next", () => {
    render(
      <MemoryRouter initialEntries={["/auth/logged-out/?next=https://evil.example.test/portal/"]}>
        <App shell="portal" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "重新登录" })).toHaveAttribute("href", "/auth/local/");
  });

  test("语言与通知弹层互斥展开, 语言菜单可切换界面语言", async () => {
    const user = userEvent.setup();
    renderShell("console");

    await user.click(screen.getByRole("button", { name: "切换语言" }));
    expect(screen.getByTestId("topbar-language-menu")).toBeVisible();
    expect(screen.getByRole("button", { name: "中文" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute("aria-pressed", "false");

    await user.click(screen.getByRole("button", { name: "通知中心" }));
    expect(screen.queryByTestId("topbar-language-menu")).not.toBeInTheDocument();
    expect(screen.getByTestId("topbar-notifications-menu")).toBeVisible();
    expect(screen.getByText("暂无新通知")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "切换语言" }));
    await user.click(screen.getByRole("button", { name: "English" }));
    expect(screen.queryByTestId("topbar-language-menu")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Switch language" })).toBeVisible();
  });

  test("点击用户身份区域时展示登出菜单", async () => {
    const user = userEvent.setup();
    renderShell("portal", "alice@example.com");

    const trigger = screen.getByRole("button", { name: "当前登录用户菜单" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    const menu = screen.getByRole("menu");
    expect(within(menu).getByRole("menuitem", { name: "安全设置" })).toHaveAttribute("href", "/portal/settings");

    const logoutForm = screen.getByRole("form", { name: "退出登录" });
    expect(logoutForm).toHaveAttribute("action", "/auth/logout/");
    expect(logoutForm).toHaveAttribute("method", "post");
    expect(within(logoutForm).getByRole("menuitem", { name: "退出登录" })).toBeVisible();
  });

  test("外部 logoutUrl 不会把登出表单带离 EasyAuth", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/portal"]}>
        <Routes>
          <Route
            element={
              <AppShell
                currentUser={{
                  displayName: "张三",
                  id: "alice@example.com",
                  logoutUrl: "https://authentik.example.test/if/session-end/easyauth/",
                }}
                mode="portal"
              />
            }
          >
            <Route path="/portal" element={<div>页面内容</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("button", { name: "当前登录用户菜单" }));

    expect(screen.getByRole("form", { name: "退出登录" })).toHaveAttribute(
      "action",
      "/auth/logout/",
    );
  });

  test("侧边栏底部展示设置入口并用分隔线隔开", () => {
    renderShell("portal");

    const footer = screen.getByLabelText("侧边栏底部操作");
    expect(within(footer).getByRole("separator")).toBeVisible();
    expect(within(footer).getByRole("link", { name: "设置" })).toHaveAttribute("href", "/portal/settings");
  });

  test("菜单切换更新共享指示灯和右侧路由动画容器", async () => {
    const user = userEvent.setup();
    renderShell("portal");

    expect(screen.getByTestId("nav-active-indicator")).toHaveAttribute("data-active-path", "/portal");
    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal");

    await user.click(screen.getByRole("link", { name: "申请权限" }));

    expect(screen.getByRole("link", { name: "申请权限" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-active-indicator")).toHaveAttribute("data-active-path", "/portal/request");
    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/request");
  });

  test("壳层布局保留 EasyTrade 基准尺寸并收敛导航圆角", () => {
    expect(layoutShellCss).toContain("height: 56px;");
    expect(layoutShellCss).toContain("grid-template-columns: 240px minmax(0, 1fr);");
    expect(layoutShellCss).toContain("width: min(1440px, 100%);");
    expect(layoutShellCss).toMatch(/\.nav-list a\s*\{[^}]*border-radius: 2px;/s);
    expect(layoutShellCss).toMatch(/\.sidebar-footer a\s*\{[^}]*border-radius: 2px;/s);
    expect(layoutShellCss).not.toMatch(/border-radius:\s*6px/);
    expect(layoutShellCss).toContain("background: rgb(var(--accent));");
  });

  test("用户菜单浮层使用 2px 圆角、hairline 边框和低阴影", () => {
    expect(layoutShellCss).toMatch(/\.user-menu-popover\s*\{[^}]*border: 1px solid rgb\(var\(--hairline\)\);/s);
    expect(layoutShellCss).toMatch(/\.user-menu-popover\s*\{[^}]*border-radius: 2px;/s);
    expect(layoutShellCss).toMatch(/\.user-menu-popover\s*\{[^}]*box-shadow: 0 8px 18px rgba\(15, 23, 42, 0\.08\);/s);
    expect(layoutShellCss).not.toContain("0 14px 32px");
  });

  test("内容区桌面保持 40px 留白且移动端防止横向溢出", () => {
    expect(layoutShellCss).toMatch(/\.content\s*\{[^}]*padding: 40px;/s);
    expect(responsiveCss).toMatch(/\.content\s*\{[^}]*padding: 28px 20px;/s);
    expect(responsiveCss).toMatch(/\.shell-body\s*\{[^}]*overflow-x: hidden;/s);
    expect(responsiveCss).toMatch(/\.content\s*\{[^}]*overflow-x: hidden;/s);
  });
});
