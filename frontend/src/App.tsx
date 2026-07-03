import { Settings } from "lucide-react";
import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useSearchParams } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ButtonLink } from "./components/ButtonLink";
import { PageHeader } from "./components/PageHeader";
import { Topbar } from "./components/shell/Topbar";
import { EmptyState } from "./components/ui/EmptyState";
import { useI18n } from "./i18n/I18nProvider";
import { ConsoleAppList } from "./pages/console/ConsoleAppList";
import { ConsoleAppWorkspace } from "./pages/console/ConsoleAppWorkspace";
import { ConsoleSettingsPage } from "./pages/console/ConsoleSettingsPage";
import { OperationsPage } from "./pages/console/OperationsPage";
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
}

export function App({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", currentUser, currentUserId = "", shell }: AppProps) {
  const isConsoleAdmin = currentUser?.role === "EasyAuth Admins";

  useEffect(() => {
    if (shell === "console" && !isConsoleAdmin) {
      window.location.replace("/errors/forbidden/");
    }
  }, [shell, isConsoleAdmin]);

  if (shell === "portal") {
    return (
      <Routes>
        <Route element={<PublicShell brandLogoUrl={brandLogoUrl} mode="portal" />}>
          <Route path="/auth/logged-out/" element={<LoggedOutPage />} />
        </Route>
        <Route element={<AppShell brandLogoUrl={brandLogoUrl} currentUser={currentUser} currentUserId={currentUserId} mode="portal" />}>
          <Route path="/portal" element={<PortalPage />} />
          <Route path="/portal/request" element={<PortalPage />} />
          <Route path="/portal/requests" element={<PortalPage />} />
          <Route path="/portal/expiring" element={<PortalPage />} />
          <Route path="/portal/settings" element={<SettingsPlaceholder mode="portal" />} />
          <Route path="*" element={<Navigate to="/portal" replace />} />
        </Route>
      </Routes>
    );
  }

  if (!isConsoleAdmin) {
    return null;
  }

  return (
    <Routes>
      <Route element={<AppShell brandLogoUrl={brandLogoUrl} currentUser={currentUser} currentUserId={currentUserId} mode="console" />}>
        <Route path="/console" element={<ConsoleAppList />} />
        <Route path="/console/apps/new" element={<AppOnboardingWizard />} />
        <Route path="/console/apps/:appKey" element={<ConsoleAppWorkspace />} />
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
  const [searchParams] = useSearchParams();
  const nextPath = localAbsolutePath(searchParams.get("next"));
  const loginHref = `/auth/login/?${new URLSearchParams({ next: nextPath }).toString()}`;

  return (
    <section className="logged-out-panel" aria-labelledby="logged-out-title">
      <p className="eyebrow">EasyAuth</p>
      <h1 id="logged-out-title">{t("loggedOut.title")}</h1>
      <p className="page-description">{t("loggedOut.description")}</p>
      <div className="logged-out-actions">
        <ButtonLink variant="primary" href={loginHref}>
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

function localAbsolutePath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/portal/";
  }
  const parsed = new URL(value, window.location.origin);
  if (parsed.origin !== window.location.origin) {
    return "/portal/";
  }
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}
