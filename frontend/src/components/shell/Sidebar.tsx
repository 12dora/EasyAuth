import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

import { ShellNav } from "./ShellNav";
import type { ShellNavGroup } from "./ShellNav";

interface SidebarProps {
  mode: "console" | "portal";
}

const consoleGroups: ShellNavGroup[] = [
  {
    label: "概览",
    links: [{ to: "/console", label: "应用" }],
  },
  {
    label: "运营",
    links: [
      { to: "/console/operations/access-requests", label: "申请运营" },
      { to: "/console/operations/access-grants", label: "授权运营" },
      { to: "/console/operations/dependency-health", label: "依赖健康" },
    ],
  },
];

const portalGroups: ShellNavGroup[] = [
  {
    label: "权限",
    links: [{ to: "/portal", label: "我的权限" }],
  },
  {
    label: "申请",
    links: [
      { to: "/portal/request", label: "申请权限" },
      { to: "/portal/requests", label: "我的申请" },
      { to: "/portal/expiring", label: "即将过期" },
    ],
  },
];

export function Sidebar({ mode }: SidebarProps) {
  const location = useLocation();
  const sidebarRef = useRef<HTMLElement>(null);
  const [indicatorStyle, setIndicatorStyle] = useState<CSSProperties>({});
  const groups = mode === "console" ? consoleGroups : portalGroups;
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
    const nav = sidebarRef.current;
    const activeLink = nav?.querySelector<HTMLElement>(`[data-nav-path="${activePath}"]`);
    if (!nav || !activeLink) {
      setIndicatorStyle({});
      return;
    }
    setIndicatorStyle({
      height: activeLink.offsetHeight,
      transform: `translateY(${activeLink.offsetTop}px)`,
    });
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
      <div className="sidebar-footer" aria-label="侧边栏底部操作">
        <hr />
        <NavLink to={settingsPath} data-nav-path={settingsPath}>
          <span>设置</span>
        </NavLink>
      </div>
    </aside>
  );
}
