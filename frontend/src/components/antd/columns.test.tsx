import { screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { AccountKind, PersonRef } from "../../lib/domain/person";
import type { Translator } from "../../lib/status";
import { AppTable, type ColumnsType } from "./AppTable";
import { peopleColumn, personColumn } from "./columns";
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
});

describe("peopleColumn", () => {
  test("多名负责人纵向堆叠姓名与部门, 本地账号次行不是 UUID", () => {
    interface App {
      key: string;
      owners: PersonRef[];
    }
    const apps: App[] = [
      {
        key: "crm",
        owners: [
          { user_id: "u-1", name: "张三", department: "捷发-安环部", account_kind: "directory" },
          { user_id: UUID, name: "系统管理员", department: "", account_kind: "local" },
        ],
      },
    ];
    const columns: ColumnsType<App> = [
      peopleColumn<App>({
        t,
        getPeople: (app) => app.owners,
      }),
    ];

    renderWithAntd(<AppTable<App> columns={columns} dataSource={apps} pagination={false} rowKey="key" />);

    expect(screen.getByText("张三")).toBeVisible();
    expect(screen.getByText("捷发-安环部")).toBeVisible();
    expect(screen.getByText("系统管理员")).toBeVisible();
    expect(screen.getByText("本地用户")).toBeVisible();
    expect(screen.queryByText(UUID)).not.toBeInTheDocument();
    expect(secondaryLineTexts().every((text) => !UUID_RE.test(text.trim()))).toBe(true);
  });
});

function secondaryLineTexts(): string[] {
  return [...document.querySelectorAll("tbody td .flex.flex-col span.truncate, tbody td .flex.flex-col code")].map(
    (node) => node.textContent ?? "",
  );
}
