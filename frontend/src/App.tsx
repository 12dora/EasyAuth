import { Settings } from "lucide-react";
import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ButtonLink } from "./components/ButtonLink";
import { PageHeader } from "./components/PageHeader";
import { Topbar } from "./components/shell/Topbar";
import { EmptyState } from "./components/ui/EmptyState";
import { useI18n } from "./i18n/I18nProvider";
import { ApprovalInstancesPage } from "./pages/console/ApprovalInstancesPage";
import { ApprovalTemplatesPage } from "./pages/console/ApprovalTemplatesPage";
import { ConsoleAppList } from "./pages/console/ConsoleAppList";
import { ConsoleAppWorkspace } from "./pages/console/ConsoleAppWorkspace";
import { ConsoleSettingsPage } from "./pages/console/ConsoleSettingsPage";
import { ConsoleTeamDetail } from "./pages/console/ConsoleTeamDetail";
import { ConsoleTeamList } from "./pages/console/ConsoleTeamList";
import { OperationsPage } from "./pages/console/OperationsPage";
import { ConsolePeopleList } from "./pages/console/lifecycle/ConsolePeopleList";
import { HandoverTaskDetail } from "./pages/console/lifecycle/HandoverTaskDetail";
import { HandoverTaskList } from "./pages/console/lifecycle/HandoverTaskList";
import { OnboardingPage } from "./pages/console/lifecycle/OnboardingPage";
import { AppOnboardingWizard } from "./pages/console/onboarding/AppOnboardingWizard";
import { PortalPage } from "./pages/portal/PortalPage";

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
          <Route path="/portal" element={<PortalPage view="grants" />} />
          <Route path="/portal/request" element={<PortalPage view="request" />} />
          <Route path="/portal/requests" element={<PortalPage view="requests" />} />
          <Route path="/portal/expiring" element={<PortalPage view="expiring" />} />
          <Route path="/portal/approvals" element={<PortalPage view="approvals" />} />
          <Route path="/portal/settings" element={<SettingsPlaceholder mode="portal" />} />
          <Route path="*" element={<Navigate to="/portal" replace />} />
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
        <Route path="/console" element={<ConsoleAppList />} />
        {/* 创建应用仅超管; 非超管深链回应用列表, API 仍为最终权威。 */}
        <Route path="/console/apps/new" element={isSuperuser ? <AppOnboardingWizard /> : <Navigate to="/console" replace />} />
        <Route path="/console/apps/:appKey" element={<ConsoleAppWorkspace />} />
        <Route path="/console/teams" element={<ConsoleTeamList />} />
        <Route path="/console/teams/:teamId" element={<ConsoleTeamDetail />} />
        <Route path="/console/people" element={<ConsolePeopleList />} />
        <Route path="/console/lifecycle/handover-tasks" element={<HandoverTaskList />} />
        <Route path="/console/lifecycle/handover-tasks/:taskId" element={<HandoverTaskDetail />} />
        <Route path="/console/lifecycle/onboarding" element={<OnboardingPage />} />
        <Route path="/console/approval-templates" element={<ApprovalTemplatesPage />} />
        <Route path="/console/operations/approval-instances" element={<ApprovalInstancesPage />} />
        <Route path="/console/operations/:section" element={<OperationsPage />} />
        <Route path="/console/operations" element={<Navigate to="/console/operations/access-requests" replace />} />
        <Route path="/console/settings" element={<ConsoleSettingsPage />} />
        <Route path="*" element={<Navigate to="/console" replace />} />
      </Route>
    </Routes>
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
        <ButtonLink variant="primary" href="/auth/local/">
          {t("loggedOut.login")}
        </ButtonLink>
        <ButtonLink href="/portal/">{t("loggedOut.backToPortal")}</ButtonLink>
      </div>
    </section>
  );
}

function SettingsPlaceholder({ mode }: { mode: "console" | "portal" }) {
  const { t } = useI18n();

  return (
    <section className="space-y-6">
      <PageHeader
        eyebrow={t("settingsPlaceholder.eyebrow")}
        title={mode === "console" ? t("settingsPlaceholder.console.title") : t("settingsPlaceholder.portal.title")}
        description={t("settingsPlaceholder.description")}
      />
      <EmptyState
        icon={<Settings size={18} aria-hidden="true" />}
        title={t("settingsPlaceholder.emptyTitle")}
        description={t("settingsPlaceholder.emptyDescription")}
      />
    </section>
  );
}
