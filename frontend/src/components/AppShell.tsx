import { Outlet, useLocation } from "react-router-dom";

import type { CurrentUser } from "../App";
import { Sidebar } from "./shell/Sidebar";
import { Topbar } from "./shell/Topbar";

interface AppShellProps {
  mode: "console" | "portal";
  currentUser?: CurrentUser;
  currentUserId?: string;
  brandLogoUrl?: string;
}

export function AppShell({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", currentUser, currentUserId = "", mode }: AppShellProps) {
  const location = useLocation();
  const shellUser = currentUser ?? (currentUserId ? { id: currentUserId } : undefined);

  return (
    <div className="app-shell">
      <Topbar brandLogoUrl={brandLogoUrl} currentUser={shellUser} mode={mode} />
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
