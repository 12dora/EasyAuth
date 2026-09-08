import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { I18nProvider, useI18n } from "./I18nProvider";

function DateTimeProbe({ value }: { value: string }) {
  const { formatDateTime, locale } = useI18n();
  return (
    <span data-testid={`formatted-${locale}`}>
      {formatDateTime(value)}|{formatDateTime(value)}|{formatDateTime(value)}
    </span>
  );
}

function LocaleProbe() {
  const { locale, setLocale } = useI18n();
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <button type="button" onClick={() => setLocale("zh-CN")}>
        切换中文
      </button>
    </div>
  );
}

describe("I18nProvider", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.localStorage.clear();
  });

  test("首帧即根据存储语言同步 html lang(FF-11)", () => {
    window.localStorage.setItem("easyauth.locale", "en");

    render(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );

    expect(document.documentElement.lang).toBe("en");
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
  });

  test("切换语言时 html lang 随状态更新(FF-11)", async () => {
    window.localStorage.setItem("easyauth.locale", "en");
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );

    expect(document.documentElement.lang).toBe("en");
    await user.click(screen.getByRole("button", { name: "切换中文" }));
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
  });

  test("存储读取被拒绝时使用默认语言继续渲染", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    render(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );

    expect(document.documentElement.lang).toBe("zh-CN");
    expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
  });

  test("存储写入被拒绝时仍更新内存语言状态", async () => {
    window.localStorage.setItem("easyauth.locale", "en");
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    const user = userEvent.setup();

    render(
      <I18nProvider>
        <LocaleProbe />
      </I18nProvider>,
    );

    await user.click(screen.getByRole("button", { name: "切换中文" }));

    expect(document.documentElement.lang).toBe("zh-CN");
    expect(screen.getByTestId("locale")).toHaveTextContent("zh-CN");
  });

  test("formatDateTime 按语言复用同一个 Intl 格式化器", () => {
    const DateTimeFormat = Intl.DateTimeFormat;
    const constructed: string[] = [];
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(function MockDateTimeFormat(
      locale?: string,
      options?: Intl.DateTimeFormatOptions,
    ) {
      constructed.push(String(locale));
      return new DateTimeFormat(locale, options);
    } as unknown as typeof Intl.DateTimeFormat);

    render(
      <I18nProvider>
        <DateTimeProbe value="2026-09-08T10:00:00Z" />
      </I18nProvider>,
    );

    // 三次格式化只该构造一次: 构造一个 DateTimeFormat 比用它格式化一次贵 40 倍以上,
    // 而时间列每行每列都要调一次 formatDateTime。
    expect(constructed.filter((locale) => locale === "zh-CN")).toHaveLength(1);
    expect(screen.getByTestId("formatted-zh-CN").textContent?.split("|")).toHaveLength(3);
  });
});
