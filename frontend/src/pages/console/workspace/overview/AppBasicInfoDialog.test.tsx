import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { I18nProvider } from "../../../../i18n/I18nProvider";
import type { AppSummary } from "../../../../lib/domain";
import { AppBasicInfoDialog } from "./AppBasicInfoDialog";

const APP: AppSummary = {
  id: 1,
  app_key: "easylearning",
  name: "学习工作台",
  alias: "",
  notify_head_bgcolor: "FF1A7F4C",
  description: "",
};

test("编辑基本信息可提交通知色带", async () => {
  const onSubmit = vi.fn();
  const user = userEvent.setup();
  render(
    <I18nProvider>
      <AppBasicInfoDialog
        app={APP}
        errorMessage=""
        isSubmitting={false}
        onClose={() => undefined}
        onSubmit={onSubmit}
      />
    </I18nProvider>,
  );

  const color = screen.getByLabelText("通知色带");
  expect(color).toHaveValue("FF1A7F4C");
  await user.clear(color);
  await user.type(color, "#c62828");
  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(onSubmit).toHaveBeenCalledWith({
    name: "学习工作台",
    alias: "",
    description: "",
    notify_head_bgcolor: "#c62828",
  });
});

test("未改色带时 PATCH 不包含 notify_head_bgcolor", async () => {
  const onSubmit = vi.fn();
  const user = userEvent.setup();
  render(
    <I18nProvider>
      <AppBasicInfoDialog
        app={APP}
        errorMessage=""
        isSubmitting={false}
        onClose={() => undefined}
        onSubmit={onSubmit}
      />
    </I18nProvider>,
  );

  await user.click(screen.getByRole("button", { name: "保存" }));

  expect(onSubmit).toHaveBeenCalledWith({
    name: "学习工作台",
    alias: "",
    description: "",
  });
});
