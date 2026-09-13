import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent } from "react";

import type { CurrentUser } from "../../App";

const DEFAULT_LOGOUT_URL = "/auth/logout/";
/** 壳层模式在 main.tsx 启动时定死, 门户↔控制台只能整页跳转, 不能走 react-router。 */
export const CONSOLE_HOME_URL = "/console/";
export const PORTAL_HOME_URL = "/portal/";

export function useUserSummaryMenu({
  currentUser,
  mode,
  open,
  onOpenChange,
}: {
  currentUser: CurrentUser;
  mode: "console" | "portal";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuItemRefs = useRef<Array<HTMLElement | null>>([]);
  const shouldRestoreFocusRef = useRef(false);
  const logoutUrl = localLogoutUrl(currentUser.logoutUrl);
  // 控制台壳层回门户的入口收在头像菜单里, 与门户的「管理后台」镜像对称。
  const showEmployeePortalEntry = mode === "console";
  const showSecuritySettings = mode === "console";
  // 门户壳层的「管理后台」入口只信后端下发的准入能力, 不看本地化 role 字符串。
  const showAdminConsoleEntry = mode === "portal" && currentUser.canAccessConsole === true;
  // 菜单项按渲染顺序占位: 员工门户 → 安全设置(控制台)/管理后台(门户) → 退出登录。
  const employeePortalItemIndex = 0;
  const secondaryItemIndex = showEmployeePortalEntry ? 1 : 0;
  const logoutItemIndex =
    (showEmployeePortalEntry ? 1 : 0) + (showSecuritySettings || showAdminConsoleEntry ? 1 : 0);

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

  return {
    menuId,
    triggerRef,
    menuItemRefs,
    logoutUrl,
    showEmployeePortalEntry,
    showSecuritySettings,
    showAdminConsoleEntry,
    employeePortalItemIndex,
    secondaryItemIndex,
    logoutItemIndex,
    closeAndReturnFocus,
    onTriggerKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onOpenChange(true);
      }
    },
    onMenuKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
      handleUserMenuKeyDown(event, menuItemRefs.current, closeAndReturnFocus);
    },
  };
}

function handleUserMenuKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  menuItems: Array<HTMLElement | null>,
  closeAndReturnFocus: () => void,
) {
  const items = menuItems.filter((item): item is HTMLElement => item !== null);
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
}

export function localLogoutUrl(value: string | undefined): string {
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

export function firstPresent(...values: Array<string | undefined>): string {
  for (const value of values) {
    const normalizedValue = value?.trim();
    if (normalizedValue) {
      return normalizedValue;
    }
  }
  return "";
}
