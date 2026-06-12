import { Bell, Globe2 } from "lucide-react";

import type { CurrentUser } from "../../App";
import { UserSummary } from "./UserSummary";

interface TopbarProps {
  brandLogoUrl: string;
  currentUser?: CurrentUser;
  mode: "console" | "portal";
}

export function Topbar({ brandLogoUrl, currentUser, mode }: TopbarProps) {
  const shellTitle = currentUser ? (mode === "console" ? "管理控制台" : "员工门户") : "统一权限中心";

  return (
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
          {currentUser ? (
            <>
              <span className="topbar-divider" aria-hidden="true" />
              <UserSummary currentUser={currentUser} mode={mode} />
            </>
          ) : null}
        </div>
      </div>
    </header>
  );
}
