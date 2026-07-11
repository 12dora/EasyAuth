import { LogOut, ShieldCheck } from "lucide-react";
import { useId } from "react";
import { Link } from "react-router-dom";

import type { CurrentUser } from "../../App";
import { useI18n } from "../../i18n/I18nProvider";
import { readCsrfToken } from "../../lib/api";

const DEFAULT_LOGOUT_URL = "/auth/logout/";

interface UserSummaryProps {
  currentUser: CurrentUser;
  mode: "console" | "portal";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserSummary({ currentUser, mode, open, onOpenChange }: UserSummaryProps) {
  const { t } = useI18n();
  const menuId = useId();
  const userName = firstPresent(
    currentUser.displayName,
    mode === "console" ? t("shell.user.consoleFallback") : t("shell.user.portalFallback"),
  );
  const userRole = firstPresent(currentUser.role, t("shell.user.ungrouped"));
  const logoutUrl = localLogoutUrl(currentUser.logoutUrl);
  const avatarUrl = safeAvatarUrl(currentUser.avatarUrl);
  const securityHref = mode === "console" ? "/console/settings" : "/portal/settings";
  const avatarLabel = userName.slice(0, 1).toUpperCase();
  const csrfToken = readCsrfToken();

  return (
    <div className="user-menu">
      <button
        type="button"
        className="user-menu-trigger"
        aria-label={t("shell.userMenu")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => onOpenChange(!open)}
      >
        <span className="user-summary">
          <strong>{userName}</strong>
          <span>{userRole}</span>
        </span>
        {avatarUrl ? (
          <img className="avatar avatar-image" src={avatarUrl} alt={t("shell.user.avatarAlt", { name: userName })} />
        ) : (
          <span className="avatar" aria-hidden="true">
            {avatarLabel}
          </span>
        )}
      </button>
      {open ? (
        <div className="user-menu-popover topbar-popover" id={menuId} data-open="true" role="menu">
          <Link className="user-menu-item" to={securityHref} role="menuitem" onClick={() => onOpenChange(false)}>
            <ShieldCheck size={15} aria-hidden="true" />
            <span>{t("shell.securitySettings")}</span>
          </Link>
          <form action={logoutUrl} aria-label={t("shell.logout")} method="post">
            {csrfToken ? <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} /> : null}
            <button type="submit" className="user-menu-item user-menu-item-danger" role="menuitem">
              <LogOut size={15} aria-hidden="true" />
              <span>{t("shell.logout")}</span>
            </button>
          </form>
        </div>
      ) : null}
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

/**
 * 头像 URL 硬化, 与 localLogoutUrl 保持同一处理口径(正本清源):
 * 仅接受同源相对路径(以 / 开头, 但非 //、不含反斜杠)或 https 绝对地址;
 * data:/javascript:/http: 等一律回退为首字母头像(返回 undefined)。
 */
function safeAvatarUrl(value: string | undefined): string | undefined {
  const normalizedValue = value?.trim();
  if (!normalizedValue) {
    return undefined;
  }
  if (normalizedValue.includes("\\")) {
    return undefined;
  }
  if (normalizedValue.startsWith("/") && !normalizedValue.startsWith("//")) {
    return normalizedValue;
  }
  try {
    const parsed = new URL(normalizedValue);
    return parsed.protocol === "https:" ? normalizedValue : undefined;
  } catch {
    return undefined;
  }
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
