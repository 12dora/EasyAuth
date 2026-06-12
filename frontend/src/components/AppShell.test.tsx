import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { App } from "../App";
import { AppShell } from "./AppShell";

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
    <MemoryRouter initialEntries={[initialEntry ?? (mode === "console" ? "/console" : "/portal")]}>
      <Routes>
        <Route element={<AppShell currentUser={currentUser} currentUserId={currentUserId} mode={mode} />}>
          <Route path={mode === "console" ? "/console" : "/portal"} element={<div>页面内容</div>} />
          <Route path={mode === "console" ? "/console/settings" : "/portal/settings"} element={<div>设置页面</div>} />
          <Route path={mode === "console" ? "/console/operations/access-requests" : "/portal/request"} element={<div>申请页面</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
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
    expect(screen.queryByLabelText("当前登录用户")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /头像/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "登出当前账号" })).not.toBeInTheDocument();
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
    expect(screen.getByRole("link", { name: "重新登录" })).toHaveAttribute(
      "href",
      "/auth/login/?next=%2Fportal%2Frequests",
    );
    expect(screen.queryByText("张三")).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: "张三头像" })).not.toBeInTheDocument();
  });

  test("登出页拒绝外部 next 登录跳转", () => {
    render(
      <MemoryRouter initialEntries={["/auth/logged-out/?next=https://evil.example.test/portal/"]}>
        <App shell="portal" />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "重新登录" })).toHaveAttribute(
      "href",
      "/auth/login/?next=%2Fportal%2F",
    );
  });

  test("悬停用户身份区域时展示登出菜单", async () => {
    const user = userEvent.setup();
    renderShell("portal", "alice@example.com");

    await user.hover(screen.getByLabelText("当前登录用户"));

    const logoutForm = screen.getByRole("form", { name: "登出当前账号" });
    expect(logoutForm).toHaveAttribute("action", "/auth/logout/");
    expect(logoutForm).toHaveAttribute("method", "post");
    expect(within(logoutForm).getByRole("button", { name: "登出" })).toBeVisible();
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

    await user.hover(screen.getByLabelText("当前登录用户"));

    expect(screen.getByRole("form", { name: "登出当前账号" })).toHaveAttribute(
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
});
