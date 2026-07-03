import { Bell } from "lucide-react";

import { useI18n } from "../../i18n/I18nProvider";

interface NotificationsButtonProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** 顶栏通知中心(占位): 铃铛图标 + 空状态弹层, 样式对齐 EasyTrade。 */
export function NotificationsButton({ open, onOpenChange }: NotificationsButtonProps) {
  const { t } = useI18n();

  return (
    <div className="relative" data-testid="topbar-notifications">
      <button
        type="button"
        aria-expanded={open}
        aria-label={t("shell.notifications")}
        title={t("shell.notifications")}
        className="flex h-9 w-9 items-center justify-center bg-transparent text-ink-soft transition-colors hover:text-ink"
        onClick={() => onOpenChange(!open)}
      >
        <Bell size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div
          className="topbar-popover absolute right-0 top-11 z-30 w-[240px] rounded-md border border-ink/12 bg-paper p-3 shadow-lg"
          data-testid="topbar-notifications-menu"
        >
          <div className="text-[13px] font-medium text-ink">{t("shell.notifications")}</div>
          <div className="mt-1 text-[12px] text-ink-faint">{t("shell.notificationsEmpty")}</div>
        </div>
      ) : null}
    </div>
  );
}
