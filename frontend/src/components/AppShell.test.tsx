import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, test } from "vitest";

import { AppShell } from "./AppShell";

function renderShell(
  mode: "console" | "portal" = "console",
  currentUserId = "",
  initialEntry?: string,
) {
  render(
    <MemoryRouter initialEntries={[initialEntry ?? (mode === "console" ? "/console" : "/portal")]}>
      <Routes>
        <Route element={<AppShell currentUserId={currentUserId} mode={mode} />}>
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
    expect(screen.getByText("系统管理员")).toBeVisible();
    expect(screen.getByText("平台运营")).toBeVisible();
    expect(screen.getByLabelText("当前用户头像")).toBeVisible();
    expect(screen.getByText("概览")).toBeVisible();
    expect(screen.getByText("运营")).toBeVisible();
    expect(within(screen.getByRole("navigation", { name: "主导航" })).getByText("应用")).toBeVisible();
  });

  test("员工门户壳层展示当前用户标识和门户身份", () => {
    renderShell("portal", "alice@example.com");

    expect(screen.getByLabelText("EasyAuth 员工门户")).toBeVisible();
    expect(screen.getByText("alice@example.com")).toBeVisible();
    expect(screen.getAllByText("员工门户")).toHaveLength(2);
    expect(screen.queryByText("系统管理员")).not.toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "主导航" })).getByText("我的权限")).toBeVisible();
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
