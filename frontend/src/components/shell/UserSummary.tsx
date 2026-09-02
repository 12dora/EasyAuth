import { LayoutDashboard, LogOut, ShieldCheck } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent } from "react";
import { Link } from "react-router-dom";

import type { CurrentUser } from "../../App";
import { useI18n } from "../../i18n/I18nProvider";
import { readCsrfToken } from "../../lib/api";

const DEFAULT_LOGOUT_URL = "/auth/logout/";
/** 壳层模式在 main.tsx 启动时定死, 门户↔控制台只能整页跳转, 不能走 react-router。 */
const CONSOLE_HOME_URL = "/console/";

interface UserSummaryProps {
  currentUser: CurrentUser;
  mode: "console" | "portal";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserSummary({ currentUser, mode, open, onOpenChange }: UserSummaryProps) {
  const { t } = useI18n();
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuItemRefs = useRef<Array<HTMLElement | null>>([]);
  const shouldRestoreFocusRef = useRef(false);
  const userName = firstPresent(
    currentUser.displayName,
    mode === "console" ? t("shell.user.consoleFallback") : t("shell.user.portalFallback"),
  );
  // role 是后端下发的 code, 展示名只在 i18n 里; 顶栏不得直接印 code。
  const userRole = currentUser.role === "admin" ? t("shell.user.role.admin") : t("shell.user.role.member");
  const logoutUrl = localLogoutUrl(currentUser.logoutUrl);
  const avatarUrl = safeAvatarUrl(currentUser.avatarUrl);
  const avatarLabel = userName.slice(0, 1).toUpperCase();
  const csrfToken = readCsrfToken();
  const showSecuritySettings = mode === "console";
  // 门户壳层的「管理后台」入口只信后端下发的准入能力, 不看本地化 role 字符串。
  const showAdminConsoleEntry = mode === "portal" && currentUser.canAccessConsole === true;
  // 菜单项按渲染顺序占位; 安全设置与管理后台互斥, 同占 0 号位。
  const logoutItemIndex = showSecuritySettings || showAdminConsoleEntry ? 1 : 0;

  useEffect(() => {
    if (open) {
      window.requestAnimationFrame(() => menuItemRefs.current[0]?.focus());
      return;
    }
    if (shouldRestoreFocusRef.current) {
      shouldRestoreFocusRef.current = false;
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  }, [open]);

  const closeAndReturnFocus = () => {
    shouldRestoreFocusRef.current = true;
    onOpenChange(false);
  };

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpenChange(true);
    }
  };

  const onMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = menuItemRefs.current.filter((item): item is HTMLElement => item !== null);
    const currentIndex = items.findIndex((item) => item === document.activeElement);
    const nextIndex =
      event.key === "ArrowDown"
        ? (currentIndex + 1) % items.length
        : event.key === "ArrowUp"
          ? (currentIndex - 1 + items.length) % items.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? items.length - 1
              : -1;

    if (event.key === "Escape") {
      event.preventDefault();
      closeAndReturnFocus();
      return;
    }
    if (nextIndex === -1) {
      return;
    }
    event.preventDefault();
    items[nextIndex]?.focus();
  };

  return (
    <div className="user-menu">
      <button
        ref={triggerRef}
        type="button"
        className="user-menu-trigger"
        aria-label={t("shell.userMenu")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => onOpenChange(!open)}
        onKeyDown={onTriggerKeyDown}
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
        <div className="user-menu-popover topbar-popover" id={menuId} data-open="true" role="menu" onKeyDown={onMenuKeyDown}>
          {showSecuritySettings ? (
            <Link
              ref={(node) => {
                menuItemRefs.current[0] = node;
              }}
              className="user-menu-item"
              to="/console/settings"
              role="menuitem"
              onClick={() => onOpenChange(false)}
            >
              <ShieldCheck size={15} aria-hidden="true" />
              <span>{t("shell.securitySettings")}</span>
            </Link>
          ) : null}
          {showAdminConsoleEntry ? (
            <a
              ref={(node) => {
                menuItemRefs.current[0] = node;
              }}
              className="user-menu-item"
              href={CONSOLE_HOME_URL}
              role="menuitem"
              onClick={() => onOpenChange(false)}
            >
              <LayoutDashboard size={15} aria-hidden="true" />
              <span>{t("shell.adminConsole")}</span>
            </a>
          ) : null}
          <form action={logoutUrl} aria-label={t("shell.logout")} method="post">
            {csrfToken ? <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} /> : null}
            <button
              ref={(node) => {
                menuItemRefs.current[logoutItemIndex] = node;
              }}
              type="submit"
              className="user-menu-item user-menu-item-danger"
              role="menuitem"
            >
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
