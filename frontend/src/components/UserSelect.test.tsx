import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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
    expect(within(option).getByText("张三")).toBeVisible();
    expect(within(option).getByText("销售部")).toBeVisible();
    expect(within(option).queryByText("u-1")).toBeNull();
    const avatar = option.querySelector("img");
    expect(avatar).toHaveAttribute("src", "https://cdn.example.com/u-1.png");
    expect(avatar).toHaveAttribute("width", "20");

    // 没有部门与头像的候选只画姓名, 不塞首字母占位, 也没有空次行。
    const plainOption = screen.getByRole("option", { name: /李四/ });
    expect(within(plainOption).getByText("李四")).toBeVisible();
    expect(plainOption.querySelector("img")).toBeNull();
    expect(plainOption.querySelector("code")).toBeNull();
  });

  test("本地账号候选次行展示本地用户, 不展示 user_id", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({
        data: [{ user_id: "local-admin:admin", name: "紧急管理员", department: "", avatar_url: "" }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<UserSearchInput id="owner" value="admin" onChange={vi.fn()} />);

    await user.click(screen.getByRole("combobox"));
    const option = await screen.findByRole("option", { name: /紧急管理员/ });
    expect(within(option).getByText("本地用户")).toBeVisible();
    expect(within(option).queryByText("local-admin:admin")).toBeNull();
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

  test("选中候选后输入框显示姓名, 部门落到次要行, 不再显示用户 ID", async () => {
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
    expect(secondaryLine).not.toHaveTextContent("u-1");

    // 手输覆盖选择: 没有可信姓名, 原样显示输入内容。次行是输入框下的 <p>; 下拉里的部门不算。
    await user.clear(input);
    await user.type(input, "u-9");
    expect(input).toHaveValue("u-9");
    expect(screen.queryByText("销售部", { selector: "p" })).toBeNull();
  });

  test("不传 selectedOption 时选中后仍显示姓名与部门", async () => {
    const user = userEvent.setup();
    stubUserOptions();

    renderWithProviders(<UncontrolledSearchInputHarness />);

    const input = screen.getByRole("combobox");
    await user.type(input, "张");
    await user.click(await screen.findByRole("option", { name: /张三/ }));

    expect(screen.getByTestId("value")).toHaveTextContent("u-1");
    expect(input).toHaveValue("张三");
    const secondaryLine = screen.getByText("销售部").closest("p");
    expect(secondaryLine).toHaveTextContent("销售部");
    expect(secondaryLine).not.toHaveTextContent("u-1");
  });

  test("手输姓名失焦不按 ID 解析; 回填的 ID 才走 user_ids", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.includes("user_ids=")) {
        return jsonResponse({
          data: [{ user_id: "u-9", name: "王五", department: "研发部", avatar_url: "" }],
        });
      }
      return jsonResponse({ data: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    const typed = renderWithProviders(
      <>
        <button type="button">outside</button>
        <UncontrolledSearchInputHarness />
      </>,
    );
    await user.type(screen.getByRole("combobox"), "张");
    // 点外面关掉下拉: 若误把手输搜索词当 ID 解析, react-query 会立刻打 user_ids。
    await user.click(screen.getByRole("button", { name: "outside" }));
    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.includes("user_ids="))).toEqual([]);
    typed.unmount();

    renderWithProviders(<UserSearchInput id="owner" value="u-9" onChange={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue("王五"));
    expect(screen.getByText("研发部")).toBeVisible();
    expect(
      fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.includes("user_ids=")),
    ).toEqual(["/console/api/v1/user-options?user_ids=u-9&purpose=employee"]);
  });

  test("回填的 user_id 按 employee 口径解析成姓名", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.includes("user_ids=")) {
        return jsonResponse({
          data: [{ user_id: "u-1", name: "张三", department: "销售部", avatar_url: "" }],
        });
      }
      return jsonResponse({ data: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<UserSearchInput id="owner" value="u-1" onChange={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("combobox")).toHaveValue("张三"));
    expect(screen.getByText("销售部")).toBeVisible();
    expect(screen.queryByText("u-1")).toBeNull();
    expect(
      fetchMock.mock.calls.map(([input]) => String(input)).filter((url) => url.includes("user_ids=")),
    ).toEqual(["/console/api/v1/user-options?user_ids=u-1&purpose=employee"]);
  });

  test("按 ID 解析失败时原样显示输入值", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse({ data: [] }));
    vi.stubGlobal("fetch", fetchMock);

    renderWithProviders(<UserSearchInput id="owner" value="missing" onChange={vi.fn()} />);

    expect(screen.getByRole("combobox")).toHaveValue("missing");
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes("user_ids=missing"))).toBe(true);
    });
    expect(screen.getByRole("combobox")).toHaveValue("missing");
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

  test("缓存里的旧姓名不会盖掉后来搜到的新姓名", async () => {
    let lookupCalls = 0;
    const fetchMock = vi.fn<typeof fetch>(async (input) => {
      const url = String(input);
      if (url.includes("user_ids=")) {
        lookupCalls += 1;
        if (lookupCalls === 1) {
          return jsonResponse({ data: [{ user_id: "u-1", name: "张三(旧)", department: "", avatar_url: "" }] });
        }
        // 第二次解析一直不回来: 这时候界面上只剩缓存里的那份旧姓名和搜索见过的新姓名。
        return new Promise<Response>(() => {});
      }
      if (url.includes("q=%E6%9D%8E")) {
        return jsonResponse({ data: [{ user_id: "u-2", name: "李四", department: "", avatar_url: "" }] });
      }
      return jsonResponse({
        data: [
          { user_id: "u-1", name: "张三(新)", department: "", avatar_url: "" },
          { user_id: "u-2", name: "李四", department: "", avatar_url: "" },
        ],
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithProviders(<UserMultiSelect id="approvers" value={["u-1"]} onChange={vi.fn()} />);

    // 先由批量解析给出姓名。
    expect(await screen.findByText("张三(旧)")).toBeVisible();

    // 再搜一次: 同一个人在搜索结果里是新姓名, 它比缓存里的那份新。
    const input = screen.getByRole("combobox");
    await user.type(input, "张");
    expect(await screen.findByText("张三(新)")).toBeVisible();

    // 换个搜索词, 这个人离开搜索结果 => 又回到批量解析那条路, 而它命中的正是最早那份缓存。
    await user.clear(input);
    await user.type(input, "李");
    await waitFor(() => expect(lookupCalls).toBe(2));

    expect(screen.getByText("张三(新)")).toBeVisible();
    expect(screen.queryByText("张三(旧)")).toBeNull();
  });

  test("移除后从残留候选里重新选中, chip 仍然显示姓名", async () => {
    // 复现: 按 ID 搜到人 -> 选中 -> 移除 -> 从"还挂在那儿"的候选里再选一次。
    // 输入框已经清空, 那份候选是上一次搜索留下的占位数据(没有取回时刻), 还会挡住按 ID 的批量解析,
    // 所以这一次选中必须自己把姓名记下来, 否则 chip 会一直是裸 ID。
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ data: [{ user_id: "u-1", name: "张三", department: "销售部", avatar_url: "" }] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    renderWithProviders(<MultiSelectHarness />);

    const input = screen.getByRole("combobox");
    await user.type(input, "u-1");
    await user.click(await screen.findByRole("option", { name: /张三/ }));
    expect(await screen.findByText("张三")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "移除 张三" }));
    expect(screen.getByTestId("value")).toHaveTextContent("");

    await user.click(await screen.findByRole("option", { name: /张三/ }));

    expect(screen.getByTestId("value")).toHaveTextContent("u-1");
    expect(await screen.findByText("张三")).toBeVisible();
    expect(screen.getByRole("button", { name: "移除 张三" })).toBeVisible();
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

/** 多选也是受控的: 用例里用最小壳子接住已选 ID。 */
function MultiSelectHarness() {
  const [value, setValue] = useState<string[]>([]);
  return (
    <>
      <span data-testid="value">{value.join(",")}</span>
      <UserMultiSelect id="approvers" value={value} onChange={setValue} />
    </>
  );
}

/** 多数调用方不传 selectedOption: 组件必须自己记住刚选中的人。 */
function UncontrolledSearchInputHarness() {
  const [userId, setUserId] = useState("");
  return (
    <>
      <span data-testid="value">{userId}</span>
      <UserSearchInput id="owner" value={userId} onChange={setUserId} />
    </>
  );
}

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
