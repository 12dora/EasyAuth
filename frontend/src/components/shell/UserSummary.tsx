import { LogOut } from "lucide-react";
import { useId } from "react";

import type { CurrentUser } from "../../App";
import { readCsrfToken } from "../../lib/api";

const DEFAULT_LOGOUT_URL = "/auth/logout/";

interface UserSummaryProps {
  currentUser: CurrentUser;
  mode: "console" | "portal";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserSummary({ currentUser, mode, open, onOpenChange }: UserSummaryProps) {
  const menuId = useId();
  const userName = firstPresent(currentUser.displayName, mode === "console" ? "控制台用户" : "当前用户");
  const userRole = firstPresent(currentUser.role, "未分组");
  const logoutUrl = localLogoutUrl(currentUser.logoutUrl);
  const avatarLabel = userName.slice(0, 1).toUpperCase();
  const csrfToken = readCsrfToken();

  return (
    <div className="user-menu">
      <button
        type="button"
        className="user-menu-trigger"
        aria-label="当前登录用户菜单"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => onOpenChange(!open)}
      >
        <span className="user-summary">
          <strong>{userName}</strong>
          <span>{userRole}</span>
        </span>
        {currentUser.avatarUrl ? (
          <img className="avatar avatar-image" src={currentUser.avatarUrl} alt={`${userName}头像`} />
        ) : (
          <span className="avatar" aria-hidden="true">
            {avatarLabel}
          </span>
        )}
      </button>
      <div className="user-menu-popover" id={menuId} data-open={open}>
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
