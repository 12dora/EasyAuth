import { ConfigProvider } from "antd";
import type { Locale as AntdLocale } from "antd/es/locale";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import { useMemo, type ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { APP_ANTD_THEME } from "./theme";

const ANTD_LOCALES: Record<string, AntdLocale> = {
  "zh-CN": zhCN,
  en: enUS,
};

/*
 * autoInsertSpace: antd 默认会把两个汉字的按钮渲染成「确 定」, 与仓库自研 Button 的排版不一致, 统一关掉。
 *
 * 提到模块级常量: ConfigProvider 把 button 这类透传配置按引用比较来决定要不要换掉
 * 整个 config context(antd/es/config-provider 的 memoedConfig), 写成行内字面量会让
 * 壳层的每一次渲染都换一个新对象, 全站 antd 组件跟着白重渲染一轮。
 */
const ANTD_BUTTON_CONFIG = { autoInsertSpace: false } as const;

/**
 * 全局 antd 配置: 设计令牌主题 + 跟随 I18nProvider 的 locale。
 *
 * 必须挂在 I18nProvider 之内(见 src/main.tsx), 语言切换时 antd 内建的分页
 * 「10 条/页」「共 x 条」、筛选「确定/重置」、空态文案会随之切换。
 *
 * antd v5 默认 CSS-in-JS, 不引入 antd/dist/reset.css:
 * Tailwind preflight 已经做了 box-sizing / list / margin 重置, 再叠一层
 * antd reset 会和 Tailwind 的基础层互相覆盖。
 */
export function AppConfigProvider({ children }: { children: ReactNode }) {
  const { locale } = useI18n();
  const antdLocale = useMemo(() => ANTD_LOCALES[locale] ?? zhCN, [locale]);

  return (
    <ConfigProvider button={ANTD_BUTTON_CONFIG} locale={antdLocale} theme={APP_ANTD_THEME}>
      {children}
    </ConfigProvider>
  );
}
