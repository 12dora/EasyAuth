import { Settings } from "lucide-react";
import { Component, Fragment, lazy, Suspense, useEffect, type ErrorInfo, type ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation, useParams } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ButtonLink } from "./components/ButtonLink";
import { PageHeader } from "./components/PageHeader";
import { Topbar } from "./components/shell/Topbar";
import { EmptyState } from "./components/ui/EmptyState";
import { useI18n } from "./i18n/I18nProvider";

const ApprovalInstancesPage = lazy(() =>
  import("./pages/console/ApprovalInstancesPage").then((module) => ({ default: module.ApprovalInstancesPage })),
);
const ApprovalTemplatesPage = lazy(() =>
  import("./pages/console/ApprovalTemplatesPage").then((module) => ({ default: module.ApprovalTemplatesPage })),
);
const ConsoleAppList = lazy(() =>
  import("./pages/console/ConsoleAppList").then((module) => ({ default: module.ConsoleAppList })),
);
const ConsoleAppWorkspace = lazy(() =>
  import("./pages/console/ConsoleAppWorkspace").then((module) => ({ default: module.ConsoleAppWorkspace })),
);
const ConsoleSettingsPage = lazy(() =>
  import("./pages/console/ConsoleSettingsPage").then((module) => ({ default: module.ConsoleSettingsPage })),
);
const DepartmentGrantsPage = lazy(() =>
  import("./pages/console/DepartmentGrantsPage").then((module) => ({ default: module.DepartmentGrantsPage })),
);
const DirectGrantPage = lazy(() =>
  import("./pages/console/DirectGrantPage").then((module) => ({ default: module.DirectGrantPage })),
);
const ConsoleTeamDetail = lazy(() =>
  import("./pages/console/ConsoleTeamDetail").then((module) => ({ default: module.ConsoleTeamDetail })),
);
const ConsoleTeamList = lazy(() =>
  import("./pages/console/ConsoleTeamList").then((module) => ({ default: module.ConsoleTeamList })),
);
const OperationsPage = lazy(() =>
  import("./pages/console/OperationsPage").then((module) => ({ default: module.OperationsPage })),
);
const ConsolePeopleList = lazy(() =>
  import("./pages/console/lifecycle/ConsolePeopleList").then((module) => ({ default: module.ConsolePeopleList })),
);
const HandoverTaskDetail = lazy(() =>
  import("./pages/console/lifecycle/HandoverTaskDetail").then((module) => ({ default: module.HandoverTaskDetail })),
);
const HandoverTaskList = lazy(() =>
  import("./pages/console/lifecycle/HandoverTaskList").then((module) => ({ default: module.HandoverTaskList })),
);
const OnboardingPage = lazy(() =>
  import("./pages/console/lifecycle/OnboardingPage").then((module) => ({ default: module.OnboardingPage })),
);
const AppOnboardingWizard = lazy(() =>
  import("./pages/console/onboarding/AppOnboardingWizard").then((module) => ({ default: module.AppOnboardingWizard })),
);
const PortalPage = lazy(() => import("./pages/portal/PortalPage").then((module) => ({ default: module.PortalPage })));
const PortalHandoverList = lazy(() =>
  import("./pages/portal/PortalHandoverList").then((module) => ({ default: module.PortalHandoverList })),
);
const PortalHandoverDetail = lazy(() =>
  import("./pages/portal/PortalHandoverDetail").then((module) => ({ default: module.PortalHandoverDetail })),
);

interface AppProps {
  shell: "console" | "portal";
  currentUser?: CurrentUser;
  currentUserId?: string;
  brandLogoUrl?: string;
}

/**
 * 后端 `data-current-user-role` 下发的角色 code(src/easyauth/frontend_shell.py 的 ShellRole)。
 * 只有两个取值, 展示名一律由 i18n 决定; 后端不下发、前端也不接受展示用的角色标签。
 */
export type CurrentUserRole = "admin" | "member";

/**
 * 会话是怎么建立的(src/easyauth/frontend_shell.py 下发的 `data-current-user-auth-kind`)。
 * 只有 oidc 会话在上游 Authentik 有对应会话, 静默身份复核只对它生效;
 * local_admin 是本地管理员口令会话, 没有上游可复核。
 */
export type CurrentUserAuthKind = "oidc" | "local_admin";

export interface CurrentUser {
  avatarUrl?: string;
  displayName?: string;
  id: string;
  logoutUrl?: string;
  role: CurrentUserRole;
  /** 会话来源; 决定壳层是否对上游 Authentik 做静默身份复核。 */
  authKind: CurrentUserAuthKind;
  /** 权威超管能力; 不得用本地化 role 展示字符串做门禁。 */
  isSuperuser?: boolean;
  /** 后端判定的控制台准入能力; 门户壳层据此展示「管理后台」入口。 */
  canAccessConsole?: boolean;
}

export function App({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", currentUser, currentUserId = "", shell }: AppProps) {
  // Console shell 已由后端登录门控; owner/developer 委派管理不得被前端 role 硬编码拦死。
  // 超管专属动作(创建应用等)仍由 API is_superuser 强制; 前端用 isSuperuser 做能力展示。
  const canAccessConsole = Boolean(currentUser?.id);
  const isSuperuser = currentUser?.isSuperuser === true;

  useEffect(() => {
    if (shell === "console" && !canAccessConsole) {
      window.location.replace("/errors/forbidden/");
    }
  }, [shell, canAccessConsole]);

  if (shell === "portal") {
    return (
      <Routes>
        <Route element={<PublicShell brandLogoUrl={brandLogoUrl} mode="portal" />}>
          <Route path="/auth/logged-out/" element={<LoggedOutPage />} />
        </Route>
        <Route element={<AppShell brandLogoUrl={brandLogoUrl} currentUser={currentUser} currentUserId={currentUserId} mode="portal" />}>
          {/*
            * 五个门户视图是同一个 PortalPage 组件换 view: 按 view 打 key, 切视图仍然重挂载页面本体。
            * PortalPage 的"离职前置"对话框开关只在 grants 视图上打得开, 却是整页级状态,
            * 不重挂载就会被带到下一个视图上; 各视图的内容区本来也各自挂载, 这个 key 不多花什么。
            */}
          <Route path="/portal" element={<LazyRoute routeName="portal"><PortalPage key="grants" view="grants" /></LazyRoute>} />
          <Route path="/portal/request" element={<LazyRoute routeName="portal"><PortalPage key="request" view="request" /></LazyRoute>} />
          <Route path="/portal/requests" element={<LazyRoute routeName="portal"><PortalPage key="requests" view="requests" /></LazyRoute>} />
          <Route path="/portal/expiring" element={<LazyRoute routeName="portal"><PortalPage key="expiring" view="expiring" /></LazyRoute>} />
          <Route path="/portal/approvals" element={<LazyRoute routeName="portal"><PortalPage key="approvals" view="approvals" /></LazyRoute>} />
          <Route path="/portal/handovers" element={<LazyRoute routeName="portal"><PortalHandoverList /></LazyRoute>} />
          <Route path="/portal/handovers/:taskId" element={<LazyRoute routeName="portal"><ParamScoped param="taskId"><PortalHandoverDetail /></ParamScoped></LazyRoute>} />
          <Route path="*" element={<NotFoundRoute mode="portal" />} />
        </Route>
      </Routes>
    );
  }

  if (!canAccessConsole) {
    return null;
  }

  return (
    <Routes>
      <Route element={<AppShell brandLogoUrl={brandLogoUrl} currentUser={currentUser} currentUserId={currentUserId} mode="console" />}>
        <Route path="/console" element={<LazyRoute routeName="console"><ConsoleAppList /></LazyRoute>} />
        {/* 创建应用仅超管; 非超管深链回应用列表, API 仍为最终权威。 */}
        <Route path="/console/apps/new" element={isSuperuser ? <LazyRoute routeName="console"><AppOnboardingWizard /></LazyRoute> : <Navigate to="/console" replace />} />
        {/*
          * 工作台必须按 :appKey 打 key。
          *
          * 它自己虽然复位了编辑态(useEffect([appKey]))和面板(key={`${appKey}:${activeTab}`}),
          * 但整个工作台下面十几处 useMutation 都把 appKey 闭在 mutationFn / onSuccess 里,
          * 而 TanStack Query 会在重渲染时把这些选项更新到还在飞的那次 mutation 上:
          * 在 alpha 上点了保存、请求还没回来就切到 beta, 这次保存会打到 beta 的接口去,
          * 成功回调也会按 beta 结算(关掉 beta 的编辑器、失效错的缓存)。
          * 要在不重挂载的前提下做对, 得把目标应用绑进每一次 mutate 的入参并在结算时比对,
          * 那是工作台自己那十几个 mutation 的事; 在它们改好之前, 这里按 appKey 重挂载,
          * 让上一个应用的请求随组件一起被摘掉 —— 正确性优先于这一处的重挂载开销。
          */}
        <Route path="/console/apps/:appKey" element={<LazyRoute routeName="workspace"><ParamScoped param="appKey"><ConsoleAppWorkspace /></ParamScoped></LazyRoute>} />
        <Route path="/console/grants/direct" element={isSuperuser ? <LazyRoute routeName="console"><DirectGrantPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/grants/departments" element={isSuperuser ? <LazyRoute routeName="console"><DepartmentGrantsPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/teams" element={isSuperuser ? <LazyRoute routeName="console"><ConsoleTeamList /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/teams/:teamId" element={isSuperuser ? <LazyRoute routeName="console"><ParamScoped param="teamId"><ConsoleTeamDetail /></ParamScoped></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/people" element={isSuperuser ? <LazyRoute routeName="lifecycle"><ConsolePeopleList /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/lifecycle/handover-tasks" element={isSuperuser ? <LazyRoute routeName="lifecycle"><HandoverTaskList /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/lifecycle/handover-tasks/:taskId" element={isSuperuser ? <LazyRoute routeName="lifecycle"><ParamScoped param="taskId"><HandoverTaskDetail /></ParamScoped></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/lifecycle/onboarding" element={isSuperuser ? <LazyRoute routeName="lifecycle"><OnboardingPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/approval-templates" element={isSuperuser ? <LazyRoute routeName="console"><ApprovalTemplatesPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/operations/approval-instances" element={isSuperuser ? <LazyRoute routeName="operations"><ApprovalInstancesPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/operations/:section" element={isSuperuser ? <LazyRoute routeName="operations"><ParamScoped param="section"><OperationsPage /></ParamScoped></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/operations" element={<Navigate to="/console/operations/access-requests" replace />} />
        <Route path="/console/settings" element={<LazyRoute routeName="console"><ConsoleSettingsPage /></LazyRoute>} />
        <Route path="*" element={<NotFoundRoute mode="console" />} />
      </Route>
    </Routes>
  );
}

/*
 * 路由错误边界按 resetKey 复位, 不再用 React key。
 *
 * 用 key 复位等于每次导航(以及每次路由参数变化)都把错误边界、Suspense 和整个页面子树
 * 卸载重挂一遍 —— 而"离开出错的页面后要能恢复"本来只需要把边界自己的错误状态清掉。
 * 换成 resetKey 之后, 换页面时该重挂的仍然重挂(React 按元素类型对账:
 * 不同路由渲染的是不同的页面组件), 而同一个页面组件跨路由参数变化时可以留在原地。
 */
function LazyRoute({ children, routeName }: { children: ReactNode; routeName: "console" | "lifecycle" | "operations" | "portal" | "workspace" }) {
  const location = useLocation();

  return (
    <RouteErrorBoundary resetKey={`${routeName}:${location.pathname}`}>
      <Suspense fallback={<RouteLoadingState />}>{children}</Suspense>
    </RouteErrorBoundary>
  );
}

/**
 * 按路由参数给页面本体打 key: 参数变了只重挂载这一个页面。
 *
 * 用在"参数就是页面主体资源"的路由上 —— 页面里的对话框开关、待删除成员、
 * 表格分页/筛选这些局部状态都是绑在那个资源上的, 换了资源必须归零,
 * 否则会把上一个团队的待删除成员、上一个运维分区的筛选带到下一个页面。
 * 这与"每次导航重挂整棵子树"不同: 代价只落在真正换了资源的那一次。
 */
function ParamScoped({ children, param }: { children: ReactNode; param: string }) {
  const params = useParams();

  return <Fragment key={params[param] ?? ""}>{children}</Fragment>;
}

function RouteLoadingState() {
  const { t } = useI18n();

  return (
    <section aria-busy="true" aria-live="polite" className="space-y-4" role="status">
      <PageHeader eyebrow="EasyAuth" title={t("route.loading.title")} description={t("route.loading.description")} />
    </section>
  );
}

interface RouteErrorBoundaryProps {
  children: ReactNode;
  /** 变化即视为"换了一个页面", 边界的错误状态就地清掉; 不需要靠重挂载子树来复位。 */
  resetKey: string;
}

interface RouteErrorBoundaryState {
  hasError: boolean;
  resetKey: string;
}

class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { hasError: false, resetKey: this.props.resetKey };

  static getDerivedStateFromError(): Pick<RouteErrorBoundaryState, "hasError"> {
    return { hasError: true };
  }

  static getDerivedStateFromProps(
    props: RouteErrorBoundaryProps,
    state: RouteErrorBoundaryState,
  ): RouteErrorBoundaryState | null {
    if (props.resetKey === state.resetKey) {
      return null;
    }
    return { hasError: false, resetKey: props.resetKey };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("EasyAuth route chunk failed", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return <RouteLoadFailedState />;
    }

    return this.props.children;
  }
}

function RouteLoadFailedState() {
  const { t } = useI18n();

  return (
    <section className="space-y-6" role="alert">
      <PageHeader eyebrow="EasyAuth" title={t("route.loadFailed.title")} description={t("route.loadFailed.description")} />
      <ButtonLink to={window.location.pathname}>{t("common.retry")}</ButtonLink>
    </section>
  );
}

function PublicShell({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", mode }: { brandLogoUrl?: string; mode: "console" | "portal" }) {
  return (
    <div className="public-shell">
      <Topbar brandLogoUrl={brandLogoUrl} mode={mode} />
      <main className="public-content">
        <Outlet />
      </main>
    </div>
  );
}

function LoggedOutPage() {
  const { t } = useI18n();

  return (
    <section className="logged-out-panel" aria-labelledby="logged-out-title">
      <p className="eyebrow">EasyAuth</p>
      <h1 id="logged-out-title">{t("loggedOut.title")}</h1>
      <p className="page-description">{t("loggedOut.description")}</p>
      <div className="logged-out-actions">
        <ButtonLink variant="primary" href="/auth/sign-in/">
          {t("loggedOut.login")}
        </ButtonLink>
        <ButtonLink href="/portal/">{t("loggedOut.backToPortal")}</ButtonLink>
      </div>
    </section>
  );
}

function NotFoundRoute({ mode }: { mode: "console" | "portal" }) {
  const { t } = useI18n();
  const home = mode === "console" ? "/console" : "/portal";

  return (
    <section className="space-y-6" aria-labelledby="react-not-found-title">
      <PageHeader
        eyebrow="404"
        title={t("notFound.title")}
        description={t("notFound.description")}
        actions={<ButtonLink to={home}>{t("notFound.backHome")}</ButtonLink>}
      />
      <EmptyState
        icon={<Settings size={18} aria-hidden="true" />}
        title={t("notFound.emptyTitle")}
        description={t("notFound.emptyDescription")}
      />
    </section>
  );
}
