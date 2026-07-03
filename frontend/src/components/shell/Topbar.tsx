import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import type { CurrentUser } from "../../App";
import { useI18n } from "../../i18n/I18nProvider";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { NotificationsButton } from "./NotificationsButton";
import { UserSummary } from "./UserSummary";

interface TopbarProps {
  brandLogoUrl: string;
  currentUser?: CurrentUser;
  mode: "console" | "portal";
}

type TopbarMenu = "language" | "notifications" | "user" | null;

export function Topbar({ brandLogoUrl, currentUser, mode }: TopbarProps) {
  const { t } = useI18n();
  const location = useLocation();
  const actionsRef = useRef<HTMLDivElement>(null);
  const [openMenu, setOpenMenu] = useState<TopbarMenu>(null);
  const shellTitle = currentUser
    ? mode === "console"
      ? t("shell.console.title")
      : t("shell.portal.title")
    : t("shell.public.title");

  const menuOpenChange = (menu: Exclude<TopbarMenu, null>) => (open: boolean) => {
    setOpenMenu((current) => (open ? menu : current === menu ? null : current));
  };

  useEffect(() => {
    setOpenMenu(null);
  }, [location.pathname]);

  useEffect(() => {
    if (openMenu === null) {
      return;
    }

    function closeOnOutsidePointerDown(event: PointerEvent) {
      if (event.target instanceof Node && actionsRef.current?.contains(event.target)) {
        return;
      }
      setOpenMenu(null);
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpenMenu(null);
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [openMenu]);

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
        <div className="topbar-actions" aria-label={t("shell.topbarTools")} ref={actionsRef}>
          <LanguageSwitcher open={openMenu === "language"} onOpenChange={menuOpenChange("language")} />
          <NotificationsButton open={openMenu === "notifications"} onOpenChange={menuOpenChange("notifications")} />
          {currentUser ? (
            <>
              <span className="topbar-divider" aria-hidden="true" />
              <UserSummary
                currentUser={currentUser}
                mode={mode}
                open={openMenu === "user"}
                onOpenChange={menuOpenChange("user")}
              />
            </>
          ) : null}
        </div>
      </div>
    </header>
  );
}
