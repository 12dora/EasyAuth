import {
  Bell,
  Globe2,
} from "lucide-react";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

interface AppShellProps {
  mode: "console" | "portal";
  currentUserId?: string;
  brandLogoUrl?: string;
}

export function AppShell({ brandLogoUrl = "/assets/brand/jiefa_logo.webp", currentUserId = "", mode }: AppShellProps) {
  const location = useLocation();
  const sidebarRef = useRef<HTMLElement>(null);
  const [indicatorStyle, setIndicatorStyle] = useState<CSSProperties>({});
  const consoleGroups = [
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
  const portalGroups = [
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
  const groups = mode === "console" ? consoleGroups : portalGroups;
  const settingsPath = mode === "console" ? "/console/settings" : "/portal/settings";
  const shellTitle = mode === "console" ? "管理控制台" : "员工门户";
  const normalizedUserId = currentUserId.trim();
  const userName = normalizedUserId || (mode === "console" ? "系统管理员" : "当前用户");
  const userRole = mode === "console" ? "平台运营" : "员工门户";
  const avatarLabel = normalizedUserId ? normalizedUserId.slice(0, 1).toUpperCase() : mode === "console" ? "管" : "员";
  const navLinks = useMemo(() => groups.flatMap((group) => group.links), [groups]);
  const activePath = useMemo(() => {
    const candidates = [...navLinks.map((link) => link.to), settingsPath];
    return candidates
      .filter((path) => location.pathname === path || (path !== "/console" && path !== "/portal" && location.pathname.startsWith(path)))
      .sort((left, right) => right.length - left.length)[0] ?? (mode === "console" ? "/console" : "/portal");
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
    <div className="app-shell">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href={mode === "console" ? "/console" : "/portal"} aria-label={`EasyAuth ${shellTitle}`}>
            <img className="brand-logo" src={brandLogoUrl} alt="EasyAuth" />
            <span className="brand-copy">
              <strong>EasyAuth</strong>
              <span>{shellTitle}</span>
            </span>
          </a>
          <div className="topbar-actions" aria-label="顶部工具">
            <button className="icon-button" type="button" aria-label="切换语言" title="切换语言">
              <Globe2 size={17} />
            </button>
            <button className="icon-button" type="button" aria-label="通知中心" title="通知中心">
              <Bell size={17} />
            </button>
            <span className="topbar-divider" aria-hidden="true" />
            <div className="user-summary">
              <strong>{userName}</strong>
              <span>{userRole}</span>
            </div>
            <span className="avatar" aria-label="当前用户头像" role="img">
              {avatarLabel}
            </span>
          </div>
        </div>
      </header>
      <div className="shell-body">
        <aside className="sidebar" ref={sidebarRef}>
          <span
            className="nav-active-indicator"
            data-active-path={activePath}
            data-testid="nav-active-indicator"
            style={indicatorStyle}
            aria-hidden="true"
          />
          <nav className="nav-list" aria-label="主导航">
            {groups.map((group) => (
              <div className="nav-section" key={group.label}>
                <span className="nav-section-title">{group.label}</span>
                {group.links.map(({ to, label }) => (
                  <NavLink key={to} to={to} end={to === "/console" || to === "/portal"} data-nav-path={to}>
                    <span>{label}</span>
                  </NavLink>
                ))}
              </div>
            ))}
          </nav>
          <div className="sidebar-footer" aria-label="侧边栏底部操作">
            <hr />
            <NavLink to={settingsPath} data-nav-path={settingsPath}>
              <span>设置</span>
            </NavLink>
          </div>
        </aside>
        <main className="content">
          <div className="route-transition" data-route-pathname={location.pathname} data-testid="route-transition" key={location.pathname}>
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
