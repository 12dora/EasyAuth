import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { useI18n } from "../../i18n/I18nProvider";
import type { MessageKey } from "../../i18n/messages";
import { ShellNav } from "./ShellNav";
import type { ShellNavGroup } from "./ShellNav";

interface SidebarProps {
  mode: "console" | "portal";
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
    links: [{ to: "/console/teams", labelKey: "nav.console.teams" }],
  },
  {
    labelKey: "nav.console.operations",
    links: [
      { to: "/console/operations/access-requests", labelKey: "nav.console.accessRequests" },
      { to: "/console/operations/access-grants", labelKey: "nav.console.accessGrants" },
      { to: "/console/operations/dependency-health", labelKey: "nav.console.dependencyHealth" },
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
];

export function Sidebar({ mode }: SidebarProps) {
  const { t } = useI18n();
  const location = useLocation();
  const sidebarRef = useRef<HTMLElement>(null);
  const [indicatorStyle, setIndicatorStyle] = useState<CSSProperties>({});
  const groups = useMemo<ShellNavGroup[]>(
    () =>
      (mode === "console" ? CONSOLE_GROUPS : PORTAL_GROUPS).map((group) => ({
        label: t(group.labelKey),
        links: group.links.map((link) => ({ to: link.to, label: t(link.labelKey) })),
      })),
    [mode, t],
  );
  const settingsPath = mode === "console" ? "/console/settings" : "/portal/settings";
  const navLinks = useMemo(() => groups.flatMap((group) => group.links), [groups]);
  const activePath = useMemo(() => {
    const candidates = [...navLinks.map((link) => link.to), settingsPath];
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
      <div className="sidebar-footer" aria-label={t("shell.sidebarFooter")}>
        <hr />
        <NavLink to={settingsPath} data-nav-path={settingsPath}>
          <span>{t("shell.settings")}</span>
        </NavLink>
      </div>
    </aside>
  );
}
