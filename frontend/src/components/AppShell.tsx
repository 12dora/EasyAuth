import { Outlet, useLocation } from "react-router-dom";

import { Sidebar } from "./shell/Sidebar";
import { Topbar } from "./shell/Topbar";

interface AppShellProps {
  mode: "console" | "portal";
  currentUserId?: string;
  brandLogoUrl?: string;
}

export function AppShell({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", currentUserId = "", mode }: AppShellProps) {
  const location = useLocation();

  return (
    <div className="app-shell">
      <Topbar brandLogoUrl={brandLogoUrl} currentUserId={currentUserId} mode={mode} />
      <div className="shell-body">
        <Sidebar mode={mode} />
        <main className="content">
          <div className="route-transition" data-route-pathname={location.pathname} data-testid="route-transition" key={location.pathname}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
