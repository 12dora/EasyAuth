import { Globe } from "lucide-react";
import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent } from "react";

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
  const menuId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const shouldRestoreFocusRef = useRef(false);

  useEffect(() => {
    if (open) {
      const activeIndex = Math.max(0, LOCALE_OPTIONS.findIndex((option) => option.locale === locale));
      window.requestAnimationFrame(() => itemRefs.current[activeIndex]?.focus());
      return;
    }
    if (shouldRestoreFocusRef.current) {
      shouldRestoreFocusRef.current = false;
      window.requestAnimationFrame(() => triggerRef.current?.focus());
    }
  }, [locale, open]);

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
    const items = itemRefs.current.filter((item): item is HTMLButtonElement => item !== null);
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
    <div className="relative" data-testid="topbar-language-switcher">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls={open ? menuId : undefined}
        aria-label={t("shell.language.switch")}
        title={t("shell.language.switch")}
        className="flex h-9 w-9 items-center justify-center bg-transparent text-ink-soft transition-colors hover:text-ink"
        onClick={() => onOpenChange(!open)}
        onKeyDown={onTriggerKeyDown}
      >
        <Globe size={16} aria-hidden="true" />
      </button>
      {open ? (
        <div
          id={menuId}
          role="menu"
          className="topbar-popover absolute right-0 top-11 z-30 min-w-[132px] rounded-md border border-ink/12 bg-paper p-1 shadow-lg"
          data-testid="topbar-language-menu"
          onKeyDown={onMenuKeyDown}
        >
          {LOCALE_OPTIONS.map((option, index) => {
            const isActive = option.locale === locale;
            return (
              <button
                key={option.locale}
                ref={(node) => {
                  itemRefs.current[index] = node;
                }}
                type="button"
                role="menuitemradio"
                aria-checked={isActive}
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
