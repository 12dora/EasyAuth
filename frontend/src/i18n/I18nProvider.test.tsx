import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";

import { I18nProvider, useI18n } from "./I18nProvider";

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
});
