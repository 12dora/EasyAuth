import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import type { CurrentUser } from "../App";
import { useI18n } from "../i18n/I18nProvider";
import { cn } from "../lib/cn";
import { API_SESSION_EXPIRED_EVENT } from "../lib/api";
import { BUTTON_BASE_CLASSES, BUTTON_SIZE_CLASSES, BUTTON_VARIANT_CLASSES } from "./Button";
import { Sidebar } from "./shell/Sidebar";
import { Topbar } from "./shell/Topbar";
import { StatusBanner } from "./StatusBanner";

const BlockedAppsBanner = lazy(() =>
  import("../pages/console/lifecycle/BlockedAppsBanner").then((module) => ({ default: module.BlockedAppsBanner })),
);

interface AppShellProps {
  mode: "console" | "portal";
  currentUser?: CurrentUser;
  currentUserId?: string;
  brandLogoUrl?: string;
}

/** 通过 Outlet context 向路由页面下传当前用户标识(如门户申请页需据此排除自审批)。 */
export interface AppShellOutletContext {
  currentUserId: string;
  isSuperuser: boolean;
}

export function AppShell({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", currentUser, currentUserId = "", mode }: AppShellProps) {
  const { t } = useI18n();
  const location = useLocation();
  const queryClient = useQueryClient();
  const shellUser = currentUser ?? (currentUserId ? { id: currentUserId } : undefined);
  const [sessionExpired, setSessionExpired] = useState(false);
  const sessionExpiredRef = useRef(false);
  const loginHref = useMemo(() => loginUrlForCurrentPage(), [location.pathname, location.search, location.hash]);

  useEffect(() => {
    const onSessionExpired = () => {
      if (sessionExpiredRef.current) {
        return;
      }
      sessionExpiredRef.current = true;
      queryClient.clear();
      setSessionExpired(true);
    };
    window.addEventListener(API_SESSION_EXPIRED_EVENT, onSessionExpired);
    return () => window.removeEventListener(API_SESSION_EXPIRED_EVENT, onSessionExpired);
  }, [queryClient]);

  return (
    <div className="app-shell">
      <Topbar brandLogoUrl={brandLogoUrl} currentUser={shellUser} mode={mode} />
      <div className="shell-body">
        <Sidebar mode={mode} currentUser={shellUser} />
        <main className="content">
          {sessionExpired ? (
            <div className="mb-4">
              <StatusBanner
                live="alert"
                tone="amber"
                title={t("shell.sessionExpired.title")}
                message={t("shell.sessionExpired.description")}
              />
              <div className="mt-3">
                <a className={cn(BUTTON_BASE_CLASSES, BUTTON_VARIANT_CLASSES.primary, BUTTON_SIZE_CLASSES.md)} href={loginHref}>
                  {t("shell.sessionExpired.login")}
                </a>
              </div>
            </div>
          ) : null}
          {mode === "console" && shellUser?.isSuperuser === true ? (
            <Suspense fallback={null}>
              <BlockedAppsBanner enabled />
            </Suspense>
          ) : null}
          <div className="route-transition" data-route-pathname={location.pathname} data-testid="route-transition" key={location.pathname}>
            <Outlet context={{ currentUserId, isSuperuser: shellUser?.isSuperuser === true } satisfies AppShellOutletContext} />
          </div>
        </main>
      </div>
    </div>
  );
}

function loginUrlForCurrentPage(): string {
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return `/auth/local/?next=${encodeURIComponent(next)}`;
}
