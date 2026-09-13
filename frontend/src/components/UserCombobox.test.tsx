import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";

import type { Translator } from "../lib/status";
import {
  formatPeople,
  personNameWithDepartment,
  resolvePeople,
  useUserCombobox,
  userOptionName,
  userSecondaryLabel,
} from "./UserCombobox";

const t: Translator = (key) => (key === "user.localAccount" ? "本地用户" : String(key));

describe("formatPeople", () => {
  test("空列表展示占位符, 目录人员拼接姓名与部门, 本地账号次行不是 ID", () => {
    expect(formatPeople(undefined, t)).toBe("-");
    expect(formatPeople([], t)).toBe("-");
    expect(
      formatPeople(
        [
          { user_id: "u-1", name: "张三", department: "捷发-安环部", account_kind: "directory" },
          { user_id: "local-admin:admin", name: "紧急管理员", department: "", account_kind: "local" },
        ],
        t,
      ),
    ).toBe("张三 · 捷发-安环部、紧急管理员 · 本地用户");
  });

  test("姓名缺失时主行退回 user_id, 次行仍不展示 UUID", () => {
    const uuid = "72635468-58ca-4b3a-9c1e-aaaaaaaaaaaa";
    expect(formatPeople([{ user_id: uuid, name: "", department: "销售部", account_kind: "directory" }], t)).toBe(
      `${uuid} · 销售部`,
    );
    expect(
      formatPeople([{ user_id: uuid, name: "系统管理员", department: "", account_kind: "local" }], t),
    ).toBe("系统管理员 · 本地用户");
  });
});

describe("personNameWithDepartment", () => {
  test("空值与本地账号、目录人员分别给出一行文案", () => {
    expect(personNameWithDepartment(null, t)).toBe("-");
    expect(
      personNameWithDepartment(
        { user_id: "u-1", name: "张三", department: "捷发-安环部", account_kind: "directory" },
        t,
      ),
    ).toBe("张三 · 捷发-安环部");
    expect(
      personNameWithDepartment({ user_id: "local-admin:admin", name: "紧急管理员", account_kind: "local" }, t),
    ).toBe("紧急管理员 · 本地用户");
  });

  test("unresolved 次行留空, 不标成本地用户", () => {
    expect(userSecondaryLabel({ user_id: "missing-user", department: "", account_kind: "unresolved" }, t)).toBe("");
    expect(
      personNameWithDepartment({ user_id: "missing-user", name: "", department: "", account_kind: "unresolved" }, t),
    ).toBe("missing-user");
  });
});

describe("resolvePeople", () => {
  test("按 ID 顺序对齐已解析候选, 尚未解析的留下空姓名", () => {
    expect(resolvePeople(["u-2", "u-1"], [{ user_id: "u-1", name: "张三", department: "销售部" }])).toEqual([
      { user_id: "u-2", name: "" },
      { user_id: "u-1", name: "张三", department: "销售部" },
    ]);
    expect(userOptionName({ user_id: "u-2", name: "" })).toBe("u-2");
  });
});

describe("useUserCombobox optionSource", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("打开后走调用方 queryFn, 不打 user-options", async () => {
    const queryFn = vi.fn(async () => [{ user_id: "u-1", name: "甲", department: "销售" }]);
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    const { result } = renderHook(
      () =>
        useUserCombobox({
          query: "",
          optionSource: {
            queryKey: ["custom", "people"],
            queryFn,
            allowEmptyQuery: true,
          },
          navigateWhenClosed: false,
          openOnArrowDown: false,
          closeOnPick: true,
          onPick: () => undefined,
        }),
      { wrapper },
    );

    expect(queryFn).not.toHaveBeenCalled();
    act(() => {
      result.current.setOpen(true);
    });
    await waitFor(() =>
      expect(result.current.options).toEqual([{ user_id: "u-1", name: "甲", department: "销售" }]),
    );
    expect(queryFn).toHaveBeenCalledWith("");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
