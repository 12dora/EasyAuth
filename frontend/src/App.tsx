import { Settings } from "lucide-react";
import { Component, lazy, Suspense, useEffect, type ErrorInfo, type ReactNode } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

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

export interface CurrentUser {
  avatarUrl?: string;
  displayName?: string;
  id: string;
  logoutUrl?: string;
  role?: string;
  /** 权威超管能力; 不得用本地化 role 展示字符串做门禁。 */
  isSuperuser?: boolean;
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
          <Route path="/portal" element={<LazyRoute routeName="portal"><PortalPage view="grants" /></LazyRoute>} />
          <Route path="/portal/request" element={<LazyRoute routeName="portal"><PortalPage view="request" /></LazyRoute>} />
          <Route path="/portal/requests" element={<LazyRoute routeName="portal"><PortalPage view="requests" /></LazyRoute>} />
          <Route path="/portal/expiring" element={<LazyRoute routeName="portal"><PortalPage view="expiring" /></LazyRoute>} />
          <Route path="/portal/approvals" element={<LazyRoute routeName="portal"><PortalPage view="approvals" /></LazyRoute>} />
          <Route path="/portal/handovers" element={<LazyRoute routeName="portal"><PortalHandoverList /></LazyRoute>} />
          <Route path="/portal/handovers/:taskId" element={<LazyRoute routeName="portal"><PortalHandoverDetail /></LazyRoute>} />
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
        <Route path="/console/apps/:appKey" element={<LazyRoute routeName="workspace"><ConsoleAppWorkspace /></LazyRoute>} />
        <Route path="/console/teams" element={isSuperuser ? <LazyRoute routeName="console"><ConsoleTeamList /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/teams/:teamId" element={isSuperuser ? <LazyRoute routeName="console"><ConsoleTeamDetail /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/people" element={isSuperuser ? <LazyRoute routeName="lifecycle"><ConsolePeopleList /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/lifecycle/handover-tasks" element={isSuperuser ? <LazyRoute routeName="lifecycle"><HandoverTaskList /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/lifecycle/handover-tasks/:taskId" element={isSuperuser ? <LazyRoute routeName="lifecycle"><HandoverTaskDetail /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/lifecycle/onboarding" element={isSuperuser ? <LazyRoute routeName="lifecycle"><OnboardingPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/approval-templates" element={isSuperuser ? <LazyRoute routeName="console"><ApprovalTemplatesPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/operations/approval-instances" element={isSuperuser ? <LazyRoute routeName="operations"><ApprovalInstancesPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/operations/:section" element={isSuperuser ? <LazyRoute routeName="operations"><OperationsPage /></LazyRoute> : <Navigate to="/console" replace />} />
        <Route path="/console/operations" element={<Navigate to="/console/operations/access-requests" replace />} />
        <Route path="/console/settings" element={<LazyRoute routeName="console"><ConsoleSettingsPage /></LazyRoute>} />
        <Route path="*" element={<NotFoundRoute mode="console" />} />
      </Route>
    </Routes>
  );
}

function LazyRoute({ children, routeName }: { children: ReactNode; routeName: "console" | "lifecycle" | "operations" | "portal" | "workspace" }) {
  const location = useLocation();

  return (
    <RouteErrorBoundary key={`${routeName}:${location.pathname}`}>
      <Suspense fallback={<RouteLoadingState />}>{children}</Suspense>
    </RouteErrorBoundary>
  );
}

function RouteLoadingState() {
  const { t } = useI18n();

  return (
    <section aria-busy="true" aria-live="polite" className="space-y-4" role="status">
      <PageHeader eyebrow="EasyAuth" title={t("route.loading.title")} description={t("route.loading.description")} />
    </section>
  );
}

interface RouteErrorBoundaryState {
  hasError: boolean;
}

class RouteErrorBoundary extends Component<{ children: ReactNode }, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): RouteErrorBoundaryState {
    return { hasError: true };
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
