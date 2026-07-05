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

/** 通过 Outlet context 向路由页面下传当前用户标识(如门户申请页需据此排除自审批)。 */
export interface AppShellOutletContext {
  currentUserId: string;
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
            <Outlet context={{ currentUserId } satisfies AppShellOutletContext} />
          </div>
        </main>
      </div>
    </div>
  );
}
