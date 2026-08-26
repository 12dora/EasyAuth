import { useQuery } from "@tanstack/react-query";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { useI18n } from "../../i18n/I18nProvider";
import type { CurrentUser } from "../../App";
import type { MessageKey } from "../../i18n/messages";
import { apiRequest } from "../../lib/api";
import type { ListPayload } from "../../lib/api";
import { ShellNav } from "./ShellNav";
import type { ShellNavGroup } from "./ShellNav";

interface SidebarProps {
  mode: "console" | "portal";
  currentUser?: CurrentUser;
}

interface NavGroupSpec {
  labelKey: MessageKey;
  links: Array<{ to: string; labelKey: MessageKey }>;
}

const CONSOLE_GROUPS: NavGroupSpec[] = [
  {
    labelKey: "nav.console.overview",
    links: [{ to: "/console", labelKey: "nav.console.apps" }],
  },
  {
    labelKey: "nav.console.organization",
    links: [
      { to: "/console/teams", labelKey: "nav.console.teams" },
      { to: "/console/people", labelKey: "nav.console.people" },
      { to: "/console/lifecycle/handover-tasks", labelKey: "nav.console.handoverTasks" },
      { to: "/console/lifecycle/onboarding", labelKey: "nav.console.onboarding" },
    ],
  },
  {
    labelKey: "nav.console.approvalCenter",
    links: [{ to: "/console/approval-templates", labelKey: "nav.console.approvalTemplates" }],
  },
  {
    labelKey: "nav.console.operations",
    links: [
      { to: "/console/operations/access-requests", labelKey: "nav.console.accessRequests" },
      { to: "/console/operations/access-grants", labelKey: "nav.console.accessGrants" },
      { to: "/console/operations/approval-instances", labelKey: "nav.console.approvalInstances" },
      { to: "/console/operations/dependency-health", labelKey: "nav.console.dependencyHealth" },
      { to: "/console/operations/blocked-apps", labelKey: "nav.console.blockedApps" },
    ],
  },
];

const PORTAL_GROUPS: NavGroupSpec[] = [
  {
    labelKey: "nav.portal.permissions",
    links: [{ to: "/portal", labelKey: "nav.portal.myPermissions" }],
  },
  {
    labelKey: "nav.portal.request",
    links: [
      { to: "/portal/request", labelKey: "nav.portal.requestAccess" },
      { to: "/portal/requests", labelKey: "nav.portal.myRequests" },
      { to: "/portal/expiring", labelKey: "nav.portal.expiring" },
    ],
  },
  {
    labelKey: "nav.portal.approval",
    links: [{ to: "/portal/approvals", labelKey: "nav.portal.myApprovals" }],
  },
  {
    labelKey: "nav.portal.handovers",
    links: [{ to: "/portal/handovers", labelKey: "nav.portal.handovers" }],
  },
];

const PORTAL_APPROVALS_PATH = "/portal/approvals";
const PORTAL_HANDOVERS_PATH = "/portal/handovers";
/** 壳层模式在 main.tsx 启动时定死, 控制台↔门户只能整页跳转, 故用原生 <a> 而非 NavLink。 */
const PORTAL_HOME_URL = "/portal/";

/** 门户「待我审批」角标: 只取 pagination.total_items, 审批处理后由 ["portal","approvals"] 前缀失效自动刷新。 */
function usePendingApprovalsBadge(enabled: boolean): string {
  const query = useQuery({
    queryKey: ["portal", "approvals", "pending-badge"],
    queryFn: () => apiRequest<ListPayload<unknown>>("/portal/api/v1/me/approvals?status=pending&page=1&page_size=1"),
    enabled,
    staleTime: 30_000,
  });
  const totalItems = query.data?.pagination?.total_items ?? 0;
  if (totalItems <= 0) {
    return "";
  }
  return totalItems > 99 ? "99+" : String(totalItems);
}

/** 门户「我的交接」角标: as_assignee + as_subject 之和 > 0 时显示。 */
function useHandoverTasksBadge(enabled: boolean): string {
  const query = useQuery({
    queryKey: ["portal", "handover-tasks", "nav-badge"],
    queryFn: () =>
      apiRequest<{ handover_tasks: { as_assignee: unknown[]; as_subject: unknown[] } }>(
        "/portal/api/v1/me/handover-tasks",
      ),
    enabled,
    staleTime: 30_000,
  });
  const total =
    (query.data?.handover_tasks?.as_assignee?.length ?? 0) +
    (query.data?.handover_tasks?.as_subject?.length ?? 0);
  if (total <= 0) {
    return "";
  }
  return total > 99 ? "99+" : String(total);
}

export function Sidebar({ mode, currentUser }: SidebarProps) {
  const { t } = useI18n();
  const location = useLocation();
  const sidebarRef = useRef<HTMLElement>(null);
  const [indicatorStyle, setIndicatorStyle] = useState<CSSProperties>({});
  const pendingApprovalsBadge = usePendingApprovalsBadge(mode === "portal");
  const handoverTasksBadge = useHandoverTasksBadge(mode === "portal");
  const consoleGroups = currentUser?.isSuperuser === true ? CONSOLE_GROUPS : [CONSOLE_GROUPS[0]];
  const groups = useMemo<ShellNavGroup[]>(
    () =>
      (mode === "console" ? consoleGroups : PORTAL_GROUPS).map((group) => ({
        label: t(group.labelKey),
        links: group.links.map((link) => ({
          to: link.to,
          label: t(link.labelKey),
          badge:
            link.to === PORTAL_APPROVALS_PATH
              ? pendingApprovalsBadge
              : link.to === PORTAL_HANDOVERS_PATH
                ? handoverTasksBadge
                : undefined,
        })),
      })),
    [consoleGroups, handoverTasksBadge, mode, pendingApprovalsBadge, t],
  );
  const settingsPath = "/console/settings";
  const navLinks = useMemo(() => groups.flatMap((group) => group.links), [groups]);
  const activePath = useMemo(() => {
    const candidates = mode === "console" ? [...navLinks.map((link) => link.to), settingsPath] : navLinks.map((link) => link.to);
    return (
      candidates
        .filter((path) => location.pathname === path || (path !== "/console" && path !== "/portal" && location.pathname.startsWith(path)))
        .sort((left, right) => right.length - left.length)[0] ?? (mode === "console" ? "/console" : "/portal")
    );
  }, [location.pathname, mode, navLinks, settingsPath]);

  useEffect(() => {
    const sidebar = sidebarRef.current;
    if (!sidebar) {
      return;
    }
    // 分组导航与底部设置项处于不同 offsetParent, offsetTop 坐标系不一致,
    // 统一用相对 sidebar 的几何位置计算指示灯位移。
    const measure = () => {
      const activeLink = sidebar.querySelector<HTMLElement>(`[data-nav-path="${activePath}"]`);
      if (!activeLink) {
        setIndicatorStyle({ opacity: 0 });
        return;
      }
      const sidebarRect = sidebar.getBoundingClientRect();
      const linkRect = activeLink.getBoundingClientRect();
      setIndicatorStyle({
        height: linkRect.height,
        transform: `translateY(${linkRect.top - sidebarRect.top + sidebar.scrollTop}px)`,
      });
    };
    measure();
    const resizeObserver = new ResizeObserver(measure);
    resizeObserver.observe(sidebar);
    return () => resizeObserver.disconnect();
  }, [activePath, location.pathname]);

  return (
    <aside className="sidebar" ref={sidebarRef}>
      <span
        className="nav-active-indicator"
        data-active-path={activePath}
        data-testid="nav-active-indicator"
        style={indicatorStyle}
        aria-hidden="true"
      />
      <ShellNav groups={groups} />
      {mode === "console" ? (
        <div className="sidebar-footer" aria-label={t("shell.sidebarFooter")}>
          <hr />
          <NavLink to={settingsPath} data-nav-path={settingsPath}>
            <span>{t("shell.settings")}</span>
          </NavLink>
          <a href={PORTAL_HOME_URL}>
            <span>{t("shell.backToPortal")}</span>
          </a>
        </div>
      ) : null}
    </aside>
  );
}
