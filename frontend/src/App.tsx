import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { ConsoleAppList } from "./pages/console/ConsoleAppList";
import { ConsoleAppWorkspace } from "./pages/console/ConsoleAppWorkspace";
import { OperationsPage } from "./pages/console/OperationsPage";
import { PortalPage } from "./pages/portal/PortalPage";

interface AppProps {
  shell: "console" | "portal";
  currentUserId?: string;
  brandLogoUrl?: string;
}

export function App({ brandLogoUrl = "", currentUserId = "", shell }: AppProps) {
  if (shell === "portal") {
    return (
      <Routes>
        <Route element={<AppShell brandLogoUrl={brandLogoUrl} currentUserId={currentUserId} mode="portal" />}>
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
      <Route element={<AppShell brandLogoUrl={brandLogoUrl} currentUserId={currentUserId} mode="console" />}>
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
