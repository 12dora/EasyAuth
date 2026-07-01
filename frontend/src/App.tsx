import { Navigate, Outlet, Route, Routes, useSearchParams } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { Topbar } from "./components/shell/Topbar";
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
      <p className="eyebrow">Signed out</p>
      <h1 id="logged-out-title">已登出</h1>
      <p className="page-description">你已经退出当前 EasyAuth 会话。</p>
      <div className="logged-out-actions">
        <a className="button button-primary" href={loginHref}>
          重新登录
        </a>
        <a className="button button-secondary" href="/portal/">
          返回门户
        </a>
      </div>
    </section>
  );
}

function SettingsPlaceholder({ title }: { title: string }) {
  return (
    <section className="stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Settings</p>
          <h1>{title}</h1>
          <p className="page-description">设置入口已预留。</p>
        </div>
      </header>
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
