import { useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import type { CurrentUser } from "../App";
import { useI18n } from "../i18n/I18nProvider";
import { cn } from "../lib/cn";
import { API_SESSION_EXPIRED_EVENT } from "../lib/api";
import { signInUrlForCurrentPage } from "../lib/signInUrl";
import { BUTTON_BASE_CLASSES, BUTTON_SIZE_CLASSES, BUTTON_VARIANT_CLASSES } from "./Button";
import { Sidebar } from "./shell/Sidebar";
import { Topbar } from "./shell/Topbar";
import { useUpstreamIdentityCheck } from "./shell/useUpstreamIdentityCheck";
import type { PageNavigator } from "./shell/useUpstreamIdentityCheck";
import { StatusBanner } from "./StatusBanner";

const BlockedAppsBanner = lazy(() =>
  import("../pages/console/lifecycle/BlockedAppsBanner").then((module) => ({ default: module.BlockedAppsBanner })),
);

interface AppShellProps {
  mode: "console" | "portal";
  currentUser?: CurrentUser;
  currentUserId?: string;
  brandLogoUrl?: string;
  /** 仅供测试注入: jsdom 里 window.location.reload/assign 会抛 Not implemented。 */
  pageNavigator?: PageNavigator;
}

/** 通过 Outlet context 向路由页面下传当前用户标识(如门户申请页需据此排除自审批)。 */
export interface AppShellOutletContext {
  currentUserId: string;
  isSuperuser: boolean;
}

export function AppShell({
  brandLogoUrl = "/assets/brand/jiefa_logo.webp",
  currentUser,
  currentUserId = "",
  mode,
  pageNavigator,
}: AppShellProps) {
  const { t } = useI18n();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [sessionExpired, setSessionExpired] = useState(false);
  const sessionExpiredRef = useRef(false);
  const loginHref = useMemo(() => signInUrlForCurrentPage(), [location.pathname, location.search, location.hash]);
  // 上游身份复核只对 Authentik 会话有意义; 本地管理员会话没有上游, 401 仍走原来的提示。
  const upstreamCheckEnabled = currentUser?.authKind === "oidc";

  const showSessionExpired = useCallback(() => {
    if (sessionExpiredRef.current) {
      return;
    }
    sessionExpiredRef.current = true;
    setSessionExpired(true);
  }, []);

  useEffect(() => {
    const onSessionExpired = () => {
      if (sessionExpiredRef.current) {
        return;
      }
      queryClient.clear();
      if (upstreamCheckEnabled) {
        // 先等静默复核给结论: 上游换人要整页重载、上游已登出要跳登录页,
        // 只有复核自身失败(含超时)才回落到这块提示, 否则用户会先看到一个马上就被替换掉的横幅。
        return;
      }
      sessionExpiredRef.current = true;
      setSessionExpired(true);
    };
    window.addEventListener(API_SESSION_EXPIRED_EVENT, onSessionExpired);
    return () => window.removeEventListener(API_SESSION_EXPIRED_EVENT, onSessionExpired);
  }, [queryClient, upstreamCheckEnabled]);

  useUpstreamIdentityCheck({
    enabled: upstreamCheckEnabled,
    onSessionExpiredNotice: showSessionExpired,
    navigator: pageNavigator,
  });

  return (
    <div className="app-shell">
      <Topbar brandLogoUrl={brandLogoUrl} currentUser={currentUser} mode={mode} />
      <div className="shell-body">
        <Sidebar mode={mode} currentUser={currentUser} />
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
          {mode === "console" && currentUser?.isSuperuser === true ? (
            <Suspense fallback={null}>
              <BlockedAppsBanner enabled />
            </Suspense>
          ) : null}
          <div className="route-transition" data-route-pathname={location.pathname} data-testid="route-transition" key={location.pathname}>
            <Outlet context={{ currentUserId, isSuperuser: currentUser?.isSuperuser === true } satisfies AppShellOutletContext} />
          </div>
        </main>
      </div>
    </div>
  );
}
