import type { CurrentUser } from "../../App";
import { useI18n } from "../../i18n/I18nProvider";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { UserSummary } from "./UserSummary";

interface TopbarProps {
  brandLogoUrl: string;
  currentUser?: CurrentUser;
  mode: "console" | "portal";
}

export function Topbar({ brandLogoUrl, currentUser, mode }: TopbarProps) {
  const { t } = useI18n();
  const shellTitle = currentUser
    ? mode === "console"
      ? t("shell.console.title")
      : t("shell.portal.title")
    : t("shell.public.title");

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
        <div className="topbar-actions" aria-label={t("shell.topbarTools")}>
          <LanguageSwitcher />
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
