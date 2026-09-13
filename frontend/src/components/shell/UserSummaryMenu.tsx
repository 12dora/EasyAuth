import { LayoutDashboard, LogOut, ShieldCheck, Users } from "lucide-react";
import { Link } from "react-router-dom";

import { useI18n } from "../../i18n/I18nProvider";
import { readCsrfToken } from "../../lib/api";
import { CONSOLE_HOME_URL, PORTAL_HOME_URL, type useUserSummaryMenu } from "./useUserSummaryMenu";

export function UserSummaryMenu({
  open,
  onOpenChange,
  menu,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  menu: ReturnType<typeof useUserSummaryMenu>;
}) {
  const { t } = useI18n();
  const csrfToken = readCsrfToken();
  if (!open) {
    return null;
  }
  return (
    <div className="user-menu-popover topbar-popover" id={menu.menuId} data-open="true" role="menu" onKeyDown={menu.onMenuKeyDown}>
      {menu.showEmployeePortalEntry ? (
        <a
          ref={(node) => {
            menu.menuItemRefs.current[menu.employeePortalItemIndex] = node;
          }}
          className="user-menu-item"
          href={PORTAL_HOME_URL}
          role="menuitem"
          onClick={() => onOpenChange(false)}
        >
          <Users size={15} aria-hidden="true" />
          <span>{t("shell.employeePortal")}</span>
        </a>
      ) : null}
      {menu.showSecuritySettings ? (
        <Link
          ref={(node) => {
            menu.menuItemRefs.current[menu.secondaryItemIndex] = node;
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
      {menu.showAdminConsoleEntry ? (
        <a
          ref={(node) => {
            menu.menuItemRefs.current[menu.secondaryItemIndex] = node;
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
      <form action={menu.logoutUrl} aria-label={t("shell.logout")} method="post">
        {csrfToken ? <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken} /> : null}
        <button
          ref={(node) => {
            menu.menuItemRefs.current[menu.logoutItemIndex] = node;
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
  );
}
