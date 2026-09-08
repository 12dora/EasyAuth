import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import type { UserOption } from "./UserCombobox";
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

  test("选中候选后输入框显示姓名, 部门与用户 ID 落到次要行", async () => {
    const user = userEvent.setup();
    stubUserOptions();

    renderWithProviders(<SearchInputHarness />);

    const input = screen.getByRole("combobox");
    await user.type(input, "张");
    await user.click(await screen.findByRole("option", { name: /张三/ }));

    // 提交值仍是用户 ID, 但界面上不再出现裸 ID 当作"被选中的人"。
    expect(screen.getByTestId("value")).toHaveTextContent("u-1");
    expect(input).toHaveValue("张三");
    const secondaryLine = screen.getByText("销售部").closest("p");
    expect(secondaryLine).toHaveTextContent("销售部");
    expect(secondaryLine).toHaveTextContent("u-1");

    // 手输覆盖选择: 没有可信姓名, 原样显示输入内容。
    await user.clear(input);
    await user.type(input, "u-9");
    expect(input).toHaveValue("u-9");
    expect(screen.queryByText("销售部")).toBeNull();
  });

  test("多选 chip 按 user_ids 批量解析姓名, 未解析出姓名时才显示 ID", async () => {
    const fetchMock = stubUserOptions();

    renderWithProviders(<UserMultiSelect id="approvers" value={["u-1", "u-3"]} onChange={vi.fn()} />);

    expect(await screen.findByText("张三")).toBeVisible();
    // 目录镜像没有姓名的人只能显示 ID, 不编占位姓名。
    expect(screen.getByText("u-3")).toBeVisible();
    expect(screen.getByRole("button", { name: "移除 张三" })).toHaveClass("min-h-6", "min-w-6");

    const lookupUrls = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("user_ids="));
    expect(lookupUrls).toEqual(["/console/api/v1/user-options?user_ids=u-1%2Cu-3&purpose=employee"]);
  });

  test("审批人多选按 approver 口径批量解析: 本地管理账号不会被过滤成裸 ID", async () => {
    const fetchMock = stubUserOptions();

    renderWithProviders(
      <UserMultiSelect id="approvers" value={["u-1"]} searchPurpose="approver" onChange={vi.fn()} />,
    );

    await screen.findByText("张三");
    expect(
      fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.includes("user_ids=")),
    ).toEqual(["/console/api/v1/user-options?user_ids=u-1&purpose=approver"]);
  });
});

/** 单选输入是受控的: 用例里用最小壳子接住 value 与选中的候选项。 */
function SearchInputHarness() {
  const [userId, setUserId] = useState("");
  const [option, setOption] = useState<UserOption | null>(null);
  return (
    <>
      <span data-testid="value">{userId}</span>
      <UserSearchInput
        id="owner"
        value={userId}
        selectedOption={option}
        onChange={(value) => {
          setUserId(value);
          setOption(null);
        }}
        onSelectOption={(picked) => setOption(picked)}
      />
    </>
  );
}

function stubUserOptions() {
  const fetchMock = vi.fn<typeof fetch>(async (input) => {
    const url = String(input);
    if (url.includes("user_ids=")) {
      // 按 ID 批量解析只返回被问到的人; u-3 在目录镜像里没有姓名。
      return jsonResponse({
        data: [
          { user_id: "u-1", name: "张三", department: "销售部", avatar_url: "https://cdn.example.com/u-1.png" },
          { user_id: "u-3", name: "", department: "", avatar_url: "" },
        ],
      });
    }
    return jsonResponse({
      data: [
        { user_id: "u-1", name: "张三", department: "销售部", avatar_url: "https://cdn.example.com/u-1.png" },
        { user_id: "u-2", name: "李四", department: "", avatar_url: "" },
      ],
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
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
