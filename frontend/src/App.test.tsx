import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { App } from "./App";
import { ToastProvider } from "./components/ui/Toast";
import { I18nProvider } from "./i18n/I18nProvider";

vi.mock("./pages/console/ConsoleAppList", () => new Promise(() => undefined));

/** 路由结构用例的观察点: 页面被挂载了几次、设置页要不要抛错。 */
const routeProbes = vi.hoisted(() => ({
  workspaceMounts: 0,
  operationsMounts: 0,
  settingsThrows: false,
  /** 在途"保存": 用例决定它什么时候结算。 */
  pendingSave: Promise.resolve(),
  resolvePendingSave: () => undefined as void,
}));

/*
 * 工作台桩件按真实工作台的写法把 appKey 闭在"保存"的回调里:
 * 点保存时记下发起那一刻的 appKey, 请求回来后再按它结算。
 * 路由不重挂载的话, 这个组件实例会跨应用存活, alpha 的保存就会落到 beta 的界面上。
 */
vi.mock("./pages/console/ConsoleAppWorkspace", async () => {
  const React = await import("react");
  const { useParams } = await import("react-router-dom");
  return {
    ConsoleAppWorkspace: function ConsoleAppWorkspaceStub() {
      const { appKey = "" } = useParams();
      const [savedApp, setSavedApp] = React.useState("");
      React.useEffect(() => {
        routeProbes.workspaceMounts += 1;
      }, []);
      return React.createElement(
        "div",
        null,
        React.createElement("span", { "data-testid": "workspace-app" }, appKey),
        React.createElement("span", { "data-testid": "workspace-saved" }, savedApp),
        React.createElement(
          "button",
          {
            type: "button",
            onClick: () => {
              const target = appKey;
              routeProbes.pendingSave = routeProbes.pendingSave.then(() => {
                setSavedApp(target);
              });
            },
          },
          "保存",
        ),
      );
    },
  };
});

vi.mock("./pages/console/OperationsPage", async () => {
  const React = await import("react");
  const { useParams } = await import("react-router-dom");
  return {
    OperationsPage: function OperationsPageStub() {
      const { section = "" } = useParams();
      const [count, setCount] = React.useState(0);
      React.useEffect(() => {
        routeProbes.operationsMounts += 1;
      }, []);
      return React.createElement(
        "div",
        null,
        React.createElement("span", { "data-testid": "operations-section" }, section),
        React.createElement("span", { "data-testid": "operations-count" }, String(count)),
        React.createElement("button", { type: "button", onClick: () => setCount((current) => current + 1) }, "运维加一"),
      );
    },
  };
});

vi.mock("./pages/console/ConsoleSettingsPage", async () => {
  const React = await import("react");
  return {
    ConsoleSettingsPage: function ConsoleSettingsPageStub() {
      if (routeProbes.settingsThrows) {
        throw new Error("路由 chunk 加载失败");
      }
      return React.createElement("span", { "data-testid": "settings-page" }, "设置页");
    },
  };
});

describe("App 未知路由策略", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("门户未知路由显示 404, 不静默重定向到门户首页", () => {
    stubResizeObserver();

    renderApp("/portal/not-real", "portal");

    expect(screen.getByRole("heading", { name: "页面没有找到" })).toBeInTheDocument();
    expect(screen.getByText("未知路由已被阻断")).toBeInTheDocument();
    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/portal/not-real");
  });

  test("控制台未知路由显示 404, 不静默重定向到控制台首页", () => {
    stubResizeObserver();

    renderApp("/console/not-real", "console");

    expect(screen.getByRole("heading", { name: "页面没有找到" })).toBeInTheDocument();
    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console/not-real");
  });

  test("控制台路由懒加载期间保留 shell 并提供忙碌状态", async () => {
    stubResizeObserver();

    renderApp("/console", "console");

    expect(screen.getByTestId("route-transition")).toHaveAttribute("data-route-pathname", "/console");
    expect(await screen.findByRole("status")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("heading", { name: "正在加载页面" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation")).getByText("应用")).toBeInTheDocument();
  });
});

describe("App 路由不再靠重挂载整棵子树复位", () => {
  beforeEach(() => {
    routeProbes.workspaceMounts = 0;
    routeProbes.operationsMounts = 0;
    routeProbes.settingsThrows = false;
    routeProbes.pendingSave = new Promise<void>((resolve) => {
      routeProbes.resolvePendingSave = resolve;
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("在 alpha 上发起的保存回来时不会结算到 beta 的工作台上", async () => {
    stubResizeObserver();
    const user = userEvent.setup();
    renderApp("/console/apps/alpha", "console");

    expect(await screen.findByTestId("workspace-app")).toHaveTextContent("alpha");
    expect(routeProbes.workspaceMounts).toBe(1);
    await user.click(screen.getByRole("button", { name: "保存" }));

    // 请求还在飞的时候切到另一个应用。
    await user.click(screen.getByRole("button", { name: "去应用 beta" }));
    expect(screen.getByTestId("workspace-app")).toHaveTextContent("beta");

    await act(async () => {
      routeProbes.resolvePendingSave();
      await routeProbes.pendingSave;
    });

    // alpha 那次保存结算时, beta 的界面必须一点没动。
    expect(screen.getByTestId("workspace-saved")).toBeEmptyDOMElement();
    expect(screen.getByTestId("workspace-app")).toHaveTextContent("beta");
    // 工作台下面十几处 mutation 都把 appKey 闭在回调里, 所以这条路由按 appKey 重挂载,
    // 上一个应用的在途请求随组件一起被摘掉。
    expect(routeProbes.workspaceMounts).toBe(2);
  });

  test("运维分区是页面主体资源, 换分区仍然重挂载这一个页面", async () => {
    stubResizeObserver();
    const user = userEvent.setup();
    renderApp("/console/operations/access-requests", "console");

    expect(await screen.findByTestId("operations-section")).toHaveTextContent("access-requests");
    await user.click(screen.getByRole("button", { name: "运维加一" }));
    expect(screen.getByTestId("operations-count")).toHaveTextContent("1");
    expect(routeProbes.operationsMounts).toBe(1);

    await user.click(screen.getByRole("button", { name: "去运维审计" }));

    // 上一个分区的筛选/分页/待办对话框都绑在那个分区上, 换分区必须归零。
    expect(screen.getByTestId("operations-section")).toHaveTextContent("audit");
    expect(screen.getByTestId("operations-count")).toHaveTextContent("0");
    expect(routeProbes.operationsMounts).toBe(2);
  });

  test("页面渲染出错后导航到别的路由即恢复", async () => {
    stubResizeObserver();
    routeProbes.settingsThrows = true;
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const user = userEvent.setup();
    renderApp("/console/settings", "console");

    expect(await screen.findByRole("heading", { name: "页面加载失败" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "去应用 beta" }));

    // 错误边界靠 resetKey 就地复位; 不再需要用 React key 把整棵子树卸载重挂。
    expect(await screen.findByTestId("workspace-app")).toHaveTextContent("beta");
    expect(screen.queryByRole("heading", { name: "页面加载失败" })).not.toBeInTheDocument();
  });
});

/** 用例里的程序化导航入口; 真实壳层的侧边栏没有到具体应用/分区的链接。 */
function RouteNavProbe() {
  const navigate = useNavigate();

  return (
    <div>
      <button type="button" onClick={() => navigate("/console/apps/beta")}>
        去应用 beta
      </button>
      <button type="button" onClick={() => navigate("/console/operations/audit")}>
        去运维审计
      </button>
    </div>
  );
}

function renderApp(path: string, shell: "console" | "portal") {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <App
              shell={shell}
              currentUser={{ id: "admin", displayName: "管理员", isSuperuser: true, role: "admin", authKind: "oidc" }}
              currentUserId="admin"
            />
            <RouteNavProbe />
          </MemoryRouter>
        </ToastProvider>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

function stubResizeObserver() {
  vi.stubGlobal(
    "ResizeObserver",
    class ResizeObserver {
      observe() {}
      disconnect() {}
    },
  );
}
