import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { MESSAGES, SUPPORTED_LOCALES, type Locale, type MessageKey } from "./messages";

const LOCALE_STORAGE_KEY = "easyauth.locale";
const DEFAULT_LOCALE: Locale = "zh-CN";

type MessageVars = Record<string, string | number>;

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, vars?: MessageVars) => string;
}

function translate(locale: Locale, key: MessageKey, vars?: MessageVars): string {
  const template = MESSAGES[locale][key];
  if (!vars) {
    return template;
  }
  return template.replace(/\{(\w+)\}/g, (match, name: string) => {
    const value = vars[name];
    return value === undefined ? match : String(value);
  });
}

function readStoredLocale(): Locale {
  if (typeof window === "undefined") {
    return DEFAULT_LOCALE;
  }
  const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
  return SUPPORTED_LOCALES.includes(stored as Locale) ? (stored as Locale) : DEFAULT_LOCALE;
}

/**
 * 无 Provider 时（组件单测直接渲染）使用 zh-CN 默认上下文；
 * setLocale 只能在 Provider 内使用，误用时快速失败。
 */
const I18nContext = createContext<I18nContextValue>({
  locale: DEFAULT_LOCALE,
  setLocale: () => {
    throw new Error("setLocale 只能在 I18nProvider 内调用。");
  },
  t: (key, vars) => translate(DEFAULT_LOCALE, key, vars),
});

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStoredLocale);

  // html lang 由 locale 状态单点驱动: 首帧(含从 localStorage 恢复 en)与后续切换都同步。
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  return useContext(I18nContext);
}

/**
 * 目录数据（权限/权限组/范围/授权组）的双语显示：
 * en 且英文字段非空时用英文，否则回落中文主字段。
 */
export function localizedField(locale: Locale, zhValue: string | null | undefined, enValue: string | null | undefined): string {
  if (locale === "en" && enValue) {
    return enValue;
  }
  return zhValue ?? "";
}

export function localizedName(locale: Locale, item: { name: string; name_en?: string | null }): string {
  return localizedField(locale, item.name, item.name_en);
}
