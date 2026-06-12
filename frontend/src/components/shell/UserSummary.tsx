import { LogOut } from "lucide-react";
import { useState } from "react";

import type { CurrentUser } from "../../App";
import { readCsrfToken } from "../../lib/api";

const DEFAULT_LOGOUT_URL = "/auth/logout/";

interface UserSummaryProps {
  currentUser: CurrentUser;
  mode: "console" | "portal";
}

export function UserSummary({ currentUser, mode }: UserSummaryProps) {
  const [menuIsOpen, setMenuIsOpen] = useState(false);
  const userName = firstPresent(currentUser.displayName, mode === "console" ? "控制台用户" : "当前用户");
  const userRole = firstPresent(currentUser.role, "未分组");
  const logoutUrl = localLogoutUrl(currentUser.logoutUrl);
  const avatarLabel = userName.slice(0, 1).toUpperCase();
  const csrfToken = readCsrfToken();

  return (
    <div
      className="user-menu"
      aria-label="当前登录用户"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setMenuIsOpen(false);
        }
      }}
      onFocus={() => setMenuIsOpen(true)}
      onMouseEnter={() => setMenuIsOpen(true)}
      onMouseLeave={() => setMenuIsOpen(false)}
    >
      <div className="user-summary">
        <strong>{userName}</strong>
        <span>{userRole}</span>
      </div>
      {currentUser.avatarUrl ? (
        <img className="avatar avatar-image" src={currentUser.avatarUrl} alt={`${userName}头像`} />
      ) : (
        <span className="avatar" aria-label={`${userName}头像`} role="img">
          {avatarLabel}
        </span>
      )}
      <div className="user-menu-popover" data-open={menuIsOpen}>
        <form action={logoutUrl} aria-label="登出当前账号" method="post">
          {csrfToken ? <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} /> : null}
          <button type="submit">
            <LogOut size={15} />
            <span>登出</span>
          </button>
        </form>
      </div>
    </div>
  );
}

function localLogoutUrl(value: string | undefined): string {
  const normalizedValue = firstPresent(value, DEFAULT_LOGOUT_URL);
  if (
    normalizedValue.startsWith("/") &&
    !normalizedValue.startsWith("//") &&
    !normalizedValue.includes("\\")
  ) {
    return normalizedValue;
  }
  return DEFAULT_LOGOUT_URL;
}

function firstPresent(...values: Array<string | undefined>): string {
  for (const value of values) {
    const normalizedValue = value?.trim();
    if (normalizedValue) {
      return normalizedValue;
    }
  }
  return "";
}
