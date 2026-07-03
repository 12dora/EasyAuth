import { Globe } from "lucide-react";

import { useI18n } from "../../i18n/I18nProvider";
import type { Locale } from "../../i18n/messages";
import { cn } from "../../lib/cn";

const LOCALE_OPTIONS: Array<{ locale: Locale; labelKey: "shell.language.zh" | "shell.language.en" }> = [
  { locale: "zh-CN", labelKey: "shell.language.zh" },
  { locale: "en", labelKey: "shell.language.en" },
];

interface LanguageSwitcherProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** 顶栏语言切换: 地球图标 + 弹出菜单, 样式对齐 EasyTrade。 */
export function LanguageSwitcher({ open, onOpenChange }: LanguageSwitcherProps) {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="relative" data-testid="topbar-language-switcher">
      <button
        type="button"
        aria-expanded={open}
        aria-label={t("shell.language.switch")}
        title={t("shell.language.switch")}
        className="flex h-9 w-9 items-center justify-center bg-transparent text-ink-soft transition-colors hover:text-ink"
        onClick={() => onOpenChange(!open)}
      >
        <Globe size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div
          className="topbar-popover absolute right-0 top-11 z-30 min-w-[132px] rounded-md border border-ink/12 bg-paper p-1 shadow-lg"
          data-testid="topbar-language-menu"
        >
          {LOCALE_OPTIONS.map((option) => {
            const isActive = option.locale === locale;
            return (
              <button
                key={option.locale}
                type="button"
                aria-pressed={isActive}
                className={cn(
                  "flex w-full items-center justify-between rounded px-3 py-2 text-left text-[13px] transition-colors",
                  isActive ? "bg-paper-deep font-medium text-ink" : "text-ink-soft hover:bg-paper-deep hover:text-ink",
                )}
                onClick={() => {
                  setLocale(option.locale);
                  onOpenChange(false);
                }}
              >
                <span>{t(option.labelKey)}</span>
                {isActive ? <span className="size-1.5 rounded-full bg-accent" aria-hidden="true" /> : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
