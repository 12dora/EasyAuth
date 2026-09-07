import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { UserMultiSelect, UserSearchInput } from "./UserSelect";

describe("UserSelect", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("单选使用焦点留在输入框的 combobox 模式", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    stubUserOptions();

    renderWithProviders(<UserSearchInput id="owner" value="zhang" onChange={onChange} />);

    const input = screen.getByRole("combobox");
    await user.click(input);
    await screen.findByRole("option", { name: /张三/ });
    expect(input).toHaveAttribute("aria-controls", "owner-listbox");
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("id", "owner-listbox-option-u-1");
    expect(screen.getAllByRole("option")[0].tagName).toBe("DIV");
    expect(screen.getAllByRole("option")[0]).not.toHaveAttribute("tabindex");

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("aria-activedescendant", "owner-listbox-option-u-2");
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("u-2");
  });

  test("候选行展示姓名与部门, 有头像才渲染头像图片", async () => {
    const user = userEvent.setup();
    stubUserOptions();

    renderWithProviders(<UserSearchInput id="owner" value="zhang" onChange={vi.fn()} />);

    await user.click(screen.getByRole("combobox"));
    const option = await screen.findByRole("option", { name: /张三/ });
    expect(within(option).getByText("张三 · 销售部")).toBeVisible();
    expect(within(option).getByText("u-1")).toBeVisible();
    const avatar = option.querySelector("img");
    expect(avatar).toHaveAttribute("src", "https://cdn.example.com/u-1.png");
    expect(avatar).toHaveAttribute("width", "20");

    // 没有部门与头像的候选只画姓名, 不塞首字母占位。
    const plainOption = screen.getByRole("option", { name: /李四/ });
    expect(within(plainOption).getByText("李四")).toBeVisible();
    expect(plainOption.querySelector("img")).toBeNull();
  });

  test("从候选里选中会把完整候选项回传给调用方", async () => {
    const user = userEvent.setup();
    const onSelectOption = vi.fn();
    stubUserOptions();

    renderWithProviders(<UserSearchInput id="owner" value="zhang" onChange={vi.fn()} onSelectOption={onSelectOption} />);

    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: /张三/ }));

    expect(onSelectOption).toHaveBeenCalledWith({
      user_id: "u-1",
      name: "张三",
      department: "销售部",
      avatar_url: "https://cdn.example.com/u-1.png",
    });
  });

  test("多选 chip 删除按钮具备 24px 命中区", () => {
    renderWithProviders(<UserMultiSelect id="approvers" value={["u-1"]} onChange={vi.fn()} />);

    expect(screen.getByRole("button", { name: "移除 u-1" })).toHaveClass("min-h-6", "min-w-6");
  });
});

function stubUserOptions() {
  vi.stubGlobal(
    "fetch",
    vi.fn<typeof fetch>(async () =>
      jsonResponse({
        data: [
          { user_id: "u-1", name: "张三", department: "销售部", avatar_url: "https://cdn.example.com/u-1.png" },
          { user_id: "u-2", name: "李四", department: "", avatar_url: "" },
        ],
      }),
    ),
  );
}

function renderWithProviders(ui: ReactElement) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>{ui}</I18nProvider>
    </QueryClientProvider>,
  );
}

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
