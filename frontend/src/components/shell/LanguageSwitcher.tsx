import { useI18n } from "../../i18n/I18nProvider";
import type { Locale } from "../../i18n/messages";
import { cn } from "../../lib/cn";

const LOCALE_OPTIONS: Array<{ locale: Locale; label: string }> = [
  { locale: "zh-CN", label: "中" },
  { locale: "en", label: "EN" },
];

export function LanguageSwitcher() {
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="flex items-center rounded-[3px] border border-ink/15 p-0.5" role="group" aria-label={t("shell.language")}>
      {LOCALE_OPTIONS.map((option) => (
        <button
          key={option.locale}
          type="button"
          aria-pressed={option.locale === locale}
          className={cn(
            "h-7 min-w-9 rounded-[2px] px-2 text-xs font-semibold transition-colors",
            option.locale === locale ? "bg-ink text-paper" : "text-ink-soft hover:text-ink",
          )}
          onClick={() => setLocale(option.locale)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
