import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { renderWithAntd } from "../../components/antd/testing";
import {
  DepartmentSourcedGrants,
  departmentSourcedContent,
  departmentSourcedContentHasItems,
  departmentSourcedNoticeStatus,
  type DepartmentSourcedGrantLike,
} from "./DepartmentSourcedGrants";

/** 与组件 EXIT_TRANSITION_MS + 50ms 对齐。 */
const EXIT_UNMOUNT_FALLBACK_MS = 250;

const DEPARTMENT_GRANT: DepartmentSourcedGrantLike = {
  authorization_groups: [
    { key: "sales", name: "销售", source: "user" },
    { key: "audit", name: "审计", source: "department" },
  ],
  direct_grants: [
    {
      permission: "crm.report.view",
      permission_name: "查看报表",
      scope: "ALL",
      scope_name: "全部",
      source: "department",
    },
  ],
};

const EMPTY_GRANT: DepartmentSourcedGrantLike = {
  authorization_groups: [{ key: "sales", name: "销售", source: "user" }],
  direct_grants: [],
};

const OTHER_DEPARTMENT_GRANT: DepartmentSourcedGrantLike = {
  authorization_groups: [{ key: "finance", name: "财务", source: "department" }],
  direct_grants: [],
};

describe("DepartmentSourcedGrants", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test("departmentSourcedNoticeStatus 按就绪与查询态取值", () => {
    expect(departmentSourcedNoticeStatus(false, { isSuccess: true, isError: false })).toBe("idle");
    expect(departmentSourcedNoticeStatus(true, { isSuccess: false, isError: true })).toBe("error");
    expect(departmentSourcedNoticeStatus(true, { isSuccess: true, isError: false })).toBe("success");
    expect(departmentSourcedNoticeStatus(true, { isSuccess: false, isError: false })).toBe("pending");
  });

  test("只抽取 source=department 的组与直接权限", () => {
    const content = departmentSourcedContent(DEPARTMENT_GRANT);
    expect(departmentSourcedContentHasItems(content)).toBe(true);
    expect(content.groups.map((group) => group.key)).toEqual(["audit"]);
    expect(content.permissions.map((permission) => permission.permission)).toEqual(["crm.report.view"]);
    expect(departmentSourcedContentHasItems(departmentSourcedContent(EMPTY_GRANT))).toBe(false);
  });

  test("有组织授权时先挂载再进入 --open", async () => {
    const { rerender } = renderNotice({ status: "idle", grant: null });

    expect(screen.queryByRole("heading", { name: "来自组织授权" })).toBeNull();
    expect(document.querySelector(".department-sourced-grants")).toBeNull();

    rerender(noticeTree({ status: "success", grant: DEPARTMENT_GRANT }));

    await waitFor(() => {
      expect(document.querySelector(".department-sourced-grants--open")).not.toBeNull();
    });
    expect(screen.getByRole("heading", { name: "来自组织授权" })).toBeVisible();
    expect(screen.getByText("审计")).toBeVisible();
    expect(screen.getByText("查看报表 · 全部")).toBeVisible();
    expect(screen.getByText("由组织授权下发，请在组织授权中调整。")).toBeVisible();
  });

  test("切到没有组织授权时退出态仍挂载上一份内容", async () => {
    const { rerender } = renderNotice({ status: "success", grant: DEPARTMENT_GRANT });
    await screen.findByRole("heading", { name: "来自组织授权" });

    rerender(noticeTree({ status: "pending", grant: null, isFetching: true }));
    expect(screen.getByRole("heading", { name: "来自组织授权" })).toBeVisible();
    expect(document.querySelector(".department-sourced-grants")).toHaveClass("department-sourced-grants--open");
    expect(document.querySelector(".department-sourced-grants")).toHaveClass("department-sourced-grants--fetching");

    rerender(noticeTree({ status: "success", grant: EMPTY_GRANT }));

    await waitFor(() => {
      expect(document.querySelector(".department-sourced-grants--open")).toBeNull();
    });
    expect(document.querySelector(".department-sourced-grants")).not.toBeNull();
    expect(screen.queryByRole("heading", { name: "来自组织授权" })).toBeNull();
    expect(document.querySelector(".department-sourced-grants")?.textContent).toContain("审计");
  });

  test("换到另一份组织授权时就地替换条目并保持展开", async () => {
    const { rerender } = renderNotice({ status: "success", grant: DEPARTMENT_GRANT });
    await screen.findByRole("heading", { name: "来自组织授权" });

    rerender(noticeTree({ status: "pending", grant: DEPARTMENT_GRANT, isFetching: true }));
    expect(screen.getByText("审计")).toBeVisible();

    rerender(noticeTree({ status: "success", grant: OTHER_DEPARTMENT_GRANT }));

    await waitFor(() => {
      expect(screen.getByText("财务")).toBeVisible();
    });
    expect(screen.queryByText("审计")).toBeNull();
    expect(document.querySelector(".department-sourced-grants")).toHaveClass("department-sourced-grants--open");
  });

  test("换 identity 立刻卸掉上一份内容, 不把上一个人的组织授权留在退出态", async () => {
    const { rerender } = renderNotice({ identityKey: "u-1", status: "success", grant: DEPARTMENT_GRANT });
    await screen.findByRole("heading", { name: "来自组织授权" });

    rerender(noticeTree({ identityKey: "u-2", status: "pending", grant: null, isFetching: true }));

    expect(document.querySelector(".department-sourced-grants")).toBeNull();
    expect(screen.queryByRole("heading", { name: "来自组织授权" })).toBeNull();
    expect(screen.queryByText("审计")).toBeNull();
  });

  test("退出过渡结束后卸掉提示框", async () => {
    const { rerender } = renderNotice({ status: "success", grant: DEPARTMENT_GRANT });
    await screen.findByRole("heading", { name: "来自组织授权" });

    rerender(noticeTree({ status: "success", grant: EMPTY_GRANT }));
    await waitFor(() => {
      expect(document.querySelector(".department-sourced-grants--open")).toBeNull();
    });
    const wrapper = document.querySelector(".department-sourced-grants");
    expect(wrapper).not.toBeNull();
    expect(wrapper?.textContent).toContain("审计");

    const panel = document.querySelector(".department-sourced-grants__panel");
    expect(panel).not.toBeNull();
    fireEvent.transitionEnd(panel as HTMLElement, { propertyName: "opacity" });
    expect(document.querySelector(".department-sourced-grants")).not.toBeNull();

    fireEvent.transitionEnd(wrapper as HTMLElement, { propertyName: "transform" });
    expect(document.querySelector(".department-sourced-grants")).not.toBeNull();

    fireEvent.transitionEnd(wrapper as HTMLElement, { propertyName: "grid-template-rows" });
    expect(document.querySelector(".department-sourced-grants")).toBeNull();
    expect(screen.queryByText("审计")).toBeNull();

    fireEvent.transitionEnd(document.body, { propertyName: "opacity" });
    expect(document.querySelector(".department-sourced-grants")).toBeNull();
  });

  test("prefers-reduced-motion 下由超时兜底卸挂", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (query: string) =>
        ({
          matches: query.includes("prefers-reduced-motion"),
          media: query,
          onchange: null,
          addListener: () => undefined,
          removeListener: () => undefined,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
          dispatchEvent: () => false,
        }) as unknown as MediaQueryList,
    );

    const { rerender } = renderNotice({ status: "success", grant: DEPARTMENT_GRANT });
    await screen.findByRole("heading", { name: "来自组织授权" });

    vi.useFakeTimers();
    rerender(noticeTree({ status: "success", grant: EMPTY_GRANT }));
    expect(document.querySelector(".department-sourced-grants--open")).toBeNull();
    expect(document.querySelector(".department-sourced-grants")).not.toBeNull();
    expect(document.querySelector(".department-sourced-grants")?.textContent).toContain("审计");

    act(() => {
      vi.advanceTimersByTime(EXIT_UNMOUNT_FALLBACK_MS - 1);
    });
    expect(document.querySelector(".department-sourced-grants")).not.toBeNull();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(document.querySelector(".department-sourced-grants")).toBeNull();
    expect(screen.queryByText("审计")).toBeNull();
  });

  test("退出过程中再次展开会取消卸挂并保留内容", async () => {
    const { rerender } = renderNotice({ status: "success", grant: DEPARTMENT_GRANT });
    await screen.findByRole("heading", { name: "来自组织授权" });

    vi.useFakeTimers();
    rerender(noticeTree({ status: "success", grant: EMPTY_GRANT }));
    expect(document.querySelector(".department-sourced-grants--open")).toBeNull();
    expect(document.querySelector(".department-sourced-grants")?.textContent).toContain("审计");

    rerender(noticeTree({ status: "success", grant: OTHER_DEPARTMENT_GRANT }));
    expect(document.querySelector(".department-sourced-grants")).toHaveClass("department-sourced-grants--open");
    expect(screen.getByText("财务")).toBeVisible();
    expect(screen.queryByText("审计")).toBeNull();

    act(() => {
      vi.advanceTimersByTime(EXIT_UNMOUNT_FALLBACK_MS);
    });
    expect(document.querySelector(".department-sourced-grants")).toHaveClass("department-sourced-grants--open");
    expect(screen.getByText("财务")).toBeVisible();
  });
});

function noticeTree({
  identityKey = "u-1",
  grant,
  status,
  isFetching = false,
}: {
  identityKey?: string;
  grant: DepartmentSourcedGrantLike | null;
  status: "idle" | "pending" | "success" | "error";
  isFetching?: boolean;
}) {
  return (
    <DepartmentSourcedGrants
      identityKey={identityKey}
      grant={grant}
      status={status}
      isFetching={isFetching}
      title="来自组织授权"
      hint="由组织授权下发，请在组织授权中调整。"
      loadingLabel="正在读取该员工在此应用的现有权限…"
    />
  );
}

function renderNotice(props: Parameters<typeof noticeTree>[0]) {
  return renderWithAntd(noticeTree(props));
}
