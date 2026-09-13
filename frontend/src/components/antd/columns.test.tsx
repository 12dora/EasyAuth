import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import type { AccountKind, PersonRef } from "../../lib/domain/person";
import type { Translator } from "../../lib/status";
import { AppTable, type ColumnsType } from "./AppTable";
import { appColumn, peopleColumn, personColumn } from "./columns";
import { ANTD_TEST_TIMEOUT_MS, renderWithAntd } from "./testing";

vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

const UUID = "72635468-58ca-4b3a-9c1e-aaaaaaaaaaaa";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const t: Translator = (key) => (key === "user.localAccount" ? "本地用户" : String(key));

describe("personColumn", () => {
  test("次行展示部门或本地用户, 从不渲染 UUID", () => {
    interface Person {
      id: string;
      name: string;
      department: string;
      account_kind?: AccountKind;
    }
    const people: Person[] = [
      { id: UUID, name: "张三", department: "捷发-安环部", account_kind: "directory" },
      { id: "local-admin:break-glass", name: "紧急管理员", department: "", account_kind: "local" },
      { id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", name: "认证系统管理员", department: "", account_kind: "local" },
      { id: "u-empty-dept", name: "李四", department: "", account_kind: "directory" },
    ];
    const columns: ColumnsType<Person> = [
      personColumn<Person>({
        t,
        getName: (row) => row.name,
        getUserId: (row) => row.id,
        getDepartment: (row) => row.department,
        getAccountKind: (row) => row.account_kind,
      }),
    ];

    renderWithAntd(<AppTable<Person> columns={columns} dataSource={people} pagination={false} rowKey="id" />);

    expect(screen.getByText("张三")).toBeVisible();
    expect(screen.getByText("捷发-安环部")).toBeVisible();
    expect(screen.getByText("紧急管理员")).toBeVisible();
    expect(screen.getAllByText("本地用户").length).toBe(2);
    expect(screen.getByText("李四")).toBeVisible();
    expect(screen.queryByText(UUID)).not.toBeInTheDocument();
    expect(screen.queryByText("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")).not.toBeInTheDocument();
    expect(screen.queryByText("u-empty-dept")).not.toBeInTheDocument();
    expect(secondaryLineTexts().every((text) => !UUID_RE.test(text.trim()))).toBe(true);
  });

  test("人员列不渲染头像, 只保留姓名与部门两行", () => {
    interface Person {
      id: string;
      name: string;
      department: string;
      // 故意留着带头像的行数据, 证明列预设根本不读它。
      avatar_url: string;
    }
    const columns: ColumnsType<Person> = [
      personColumn<Person>({
        t,
        getName: (row) => row.name,
        getUserId: (row) => row.id,
        getDepartment: (row) => row.department,
      }),
    ];

    renderWithAntd(
      <AppTable<Person>
        columns={columns}
        dataSource={[
          { id: "u-1", name: "张三", department: "捷发-安环部", avatar_url: "https://cdn.example.com/zhang.png" },
          { id: "u-2", name: "李四", department: "", avatar_url: "" },
        ]}
        pagination={false}
        rowKey="id"
      />,
    );

    expect(screen.getByText("张三")).toBeVisible();
    expect(screen.getByText("捷发-安环部")).toBeVisible();
    expect(screen.getByText("李四")).toBeVisible();
    expect(document.querySelector("tbody [data-person-avatar]")).toBeNull();
    expect(document.querySelector("tbody img")).toBeNull();
  });
});

describe("peopleColumn", () => {
  test("多名负责人同一行逗号分隔, 悬停姓名展示部门或本地用户, 单元格不出 UUID", async () => {
    interface App {
      key: string;
      owners: PersonRef[];
    }
    const apps: App[] = [
      {
        key: "crm",
        owners: [
          {
            user_id: "u-1",
            name: "张三",
            department: "捷发-安环部",
            account_kind: "directory",
            avatar_url: "https://cdn.example.com/zhang.png",
          },
          { user_id: UUID, name: "系统管理员", department: "", account_kind: "local", avatar_url: "" },
        ],
      },
    ];
    const columns: ColumnsType<App> = [
      peopleColumn<App>({
        t,
        getPeople: (app) => app.owners,
      }),
    ];
    const user = userEvent.setup();

    renderWithAntd(<AppTable<App> columns={columns} dataSource={apps} pagination={false} rowKey="key" />);

    const zhang = screen.getByText("张三");
    const cell = zhang.closest("td");
    expect(cell).not.toBeNull();
    expect(within(cell as HTMLElement).getByText("张三")).toBeVisible();
    expect(within(cell as HTMLElement).getByText("系统管理员")).toBeVisible();
    expect((cell as HTMLElement).querySelector("[data-person-avatar]")).toBeNull();
    expect((cell as HTMLElement).querySelector("img")).toBeNull();
    expect(zhang.closest(".truncate")).not.toBeNull();
    expect(within(cell as HTMLElement).queryByText("捷发-安环部")).not.toBeInTheDocument();
    expect(within(cell as HTMLElement).queryByText("本地用户")).not.toBeInTheDocument();
    expect(screen.queryByText(UUID)).not.toBeInTheDocument();

    await user.hover(zhang);
    await waitFor(() => expect(visibleTooltip()).toHaveTextContent("捷发-安环部"));

    await user.unhover(zhang);
    await waitFor(() => expect(visibleTooltip()).toBeNull());
    await user.hover(screen.getByText("系统管理员"));
    await waitFor(() => expect(visibleTooltip()).toHaveTextContent("本地用户"));
  });

  test("无部门的 unresolved 人员不挂 Tooltip", async () => {
    interface App {
      key: string;
      owners: PersonRef[];
    }
    const columns: ColumnsType<App> = [
      peopleColumn<App>({
        t,
        getPeople: (app) => app.owners,
      }),
    ];
    const user = userEvent.setup();

    renderWithAntd(
      <AppTable<App>
        columns={columns}
        dataSource={[
          { key: "crm", owners: [{ user_id: "missing-user", name: "", department: "", account_kind: "unresolved", avatar_url: "" }] },
        ]}
        pagination={false}
        rowKey="key"
      />,
    );

    const name = screen.getByText("missing-user");
    await user.hover(name);
    expect(visibleTooltip()).toBeNull();
  });

  test("截断时悬停姓名只出部门 Tooltip, 悬停空白处只出全员列表", async () => {
    interface App {
      key: string;
      owners: PersonRef[];
    }
    const columns: ColumnsType<App> = [
      peopleColumn<App>({
        t,
        getPeople: (app) => app.owners,
      }),
    ];
    const user = userEvent.setup();

    renderWithAntd(
      <AppTable<App>
        columns={columns}
        dataSource={[
          {
            key: "crm",
            owners: [
              { user_id: "u-1", name: "张三", department: "捷发-安环部", account_kind: "directory", avatar_url: "" },
              { user_id: UUID, name: "系统管理员", department: "", account_kind: "local", avatar_url: "" },
            ],
          },
        ]}
        pagination={false}
        rowKey="key"
      />,
    );

    const zhang = screen.getByText("张三");
    const wrapper = zhang.closest(".truncate");
    expect(wrapper).toBeInstanceOf(HTMLElement);
    mockLayout(wrapper as HTMLElement, 200, 80);

    await user.hover(zhang);
    await waitFor(() => {
      const tips = visibleTooltips();
      expect(tips).toHaveLength(1);
      expect(tips[0]).toHaveTextContent("捷发-安环部");
    });
    expect(visibleTooltips()[0]).not.toHaveTextContent("张三 · 捷发-安环部");
    expect(visibleTooltips()[0]).not.toHaveTextContent("系统管理员");

    await user.unhover(zhang);
    await waitFor(() => expect(visibleTooltip()).toBeNull());

    fireEvent.mouseOver(wrapper as HTMLElement);
    await waitFor(() => {
      const tips = visibleTooltips();
      expect(tips).toHaveLength(1);
      expect(tips[0]).toHaveTextContent("张三 · 捷发-安环部");
      expect(tips[0]).toHaveTextContent("系统管理员 · 本地用户");
    });
  });
});

describe("appColumn", () => {
  test("超长展示名截断后悬停出全文, 与 app_key 不同时开两个 Tooltip", async () => {
    const LONG_NAME = "捷发科技-跨部门协同与客户关系管理平台（正式环境）";
    interface App {
      id: string;
      name: string;
      app_key: string;
    }
    const columns: ColumnsType<App> = [
      appColumn<App>({
        title: "应用",
        getDisplayName: (row) => row.name,
        getAppKey: (row) => row.app_key,
        width: 200,
      }),
    ];
    const user = userEvent.setup();

    renderWithAntd(
      <AppTable<App>
        columns={columns}
        dataSource={[{ id: "1", name: LONG_NAME, app_key: "easyauth-customer-relationship" }]}
        pagination={false}
        rowKey="id"
      />,
    );

    const name = screen.getByText(LONG_NAME);
    expect(name.tagName).toBe("STRONG");
    expect(name).toHaveClass("truncate");
    mockLayout(name, 240, 80);

    await user.hover(name);
    await waitFor(() => {
      const tips = visibleTooltips();
      expect(tips).toHaveLength(1);
      expect(tips[0]).toHaveTextContent(LONG_NAME);
    });

    await user.unhover(name);
    await waitFor(() => expect(visibleTooltip()).toBeNull());

    const appKey = screen.getByText("easyauth-customer-relationship");
    mockLayout(appKey, 240, 80);
    await user.hover(appKey);
    await waitFor(() => {
      const tips = visibleTooltips();
      expect(tips).toHaveLength(1);
      expect(tips[0]).toHaveTextContent("easyauth-customer-relationship");
    });
    expect(visibleTooltips()[0]).not.toHaveTextContent(LONG_NAME);
  });
});

function secondaryLineTexts(): string[] {
  return [...document.querySelectorAll("tbody td .flex.flex-col span.truncate, tbody td .flex.flex-col code")].map(
    (node) => node.textContent ?? "",
  );
}

function mockLayout(element: HTMLElement, scrollWidth: number, clientWidth: number) {
  Object.defineProperty(element, "scrollWidth", { configurable: true, get: () => scrollWidth });
  Object.defineProperty(element, "clientWidth", { configurable: true, get: () => clientWidth });
}

function visibleTooltips(): HTMLElement[] {
  return [...document.querySelectorAll(".ant-tooltip:not(.ant-tooltip-hidden)")];
}

function visibleTooltip(): HTMLElement | null {
  return visibleTooltips()[0] ?? null;
}
