import type { CurrentUser } from "../../App";
import { useI18n } from "../../i18n/I18nProvider";
import { PersonAvatar } from "../PersonAvatar";
import { UserSummaryMenu } from "./UserSummaryMenu";
import { firstPresent, useUserSummaryMenu } from "./useUserSummaryMenu";

interface UserSummaryProps {
  currentUser: CurrentUser;
  mode: "console" | "portal";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function UserSummary({ currentUser, mode, open, onOpenChange }: UserSummaryProps) {
  const { t } = useI18n();
  const menu = useUserSummaryMenu({ currentUser, mode, open, onOpenChange });
  const userName = firstPresent(
    currentUser.displayName,
    mode === "console" ? t("shell.user.consoleFallback") : t("shell.user.portalFallback"),
  );
  // role 是后端下发的 code, 展示名只在 i18n 里; 顶栏不得直接印 code。
  const userRole = currentUser.role === "admin" ? t("shell.user.role.admin") : t("shell.user.role.member");

  return (
    <div className="user-menu">
      <button
        ref={menu.triggerRef}
        type="button"
        className="user-menu-trigger"
        aria-label={t("shell.userMenu")}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menu.menuId : undefined}
        onClick={() => onOpenChange(!open)}
        onKeyDown={menu.onTriggerKeyDown}
      >
        <span className="user-summary">
          <strong>{userName}</strong>
          <span>{userRole}</span>
        </span>
        <PersonAvatar
          name={userName}
          avatarUrl={currentUser.avatarUrl}
          size={32}
          alt={t("shell.user.avatarAlt", { name: userName })}
        />
      </button>
      <UserSummaryMenu open={open} onOpenChange={onOpenChange} menu={menu} />
    </div>
  );
}
