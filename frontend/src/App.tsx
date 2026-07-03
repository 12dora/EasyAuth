import { Settings } from "lucide-react";
import { useEffect } from "react";
import { Navigate, Outlet, Route, Routes, useSearchParams } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ButtonLink } from "./components/ButtonLink";
import { PageHeader } from "./components/PageHeader";
import { Topbar } from "./components/shell/Topbar";
import { EmptyState } from "./components/ui/EmptyState";
import { ConsoleAppList } from "./pages/console/ConsoleAppList";
import { ConsoleAppWorkspace } from "./pages/console/ConsoleAppWorkspace";
import { OperationsPage } from "./pages/console/OperationsPage";
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
          <Route path="/portal/settings" element={<SettingsPlaceholder title="门户设置" />} />
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
        <Route path="/console/apps/:appKey" element={<ConsoleAppWorkspace />} />
        <Route path="/console/operations/:section" element={<OperationsPage />} />
        <Route path="/console/operations" element={<Navigate to="/console/operations/access-requests" replace />} />
        <Route path="/console/settings" element={<SettingsPlaceholder title="控制台设置" />} />
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
  const [searchParams] = useSearchParams();
  const nextPath = localAbsolutePath(searchParams.get("next"));
  const loginHref = `/auth/login/?${new URLSearchParams({ next: nextPath }).toString()}`;

  return (
    <section className="logged-out-panel" aria-labelledby="logged-out-title">
      <p className="eyebrow">EasyAuth</p>
      <h1 id="logged-out-title">已登出</h1>
      <p className="page-description">你已经退出当前 EasyAuth 会话。</p>
      <div className="logged-out-actions">
        <ButtonLink variant="primary" href={loginHref}>
          重新登录
        </ButtonLink>
        <ButtonLink href="/portal/">返回门户</ButtonLink>
      </div>
    </section>
  );
}

function SettingsPlaceholder({ title }: { title: string }) {
  return (
    <section className="space-y-6">
      <PageHeader eyebrow="设置" title={title} description="设置入口已预留，后续版本会开放具体配置项。" />
      <EmptyState
        icon={<Settings size={18} aria-hidden="true" />}
        title="暂无可配置项"
        description="该页面为设置功能预留位，当前版本还没有可调整的配置。"
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
