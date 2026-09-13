import { describe, expect, test } from "vitest";

import type { PersonRef } from "../../lib/domain/person";
import type { Translator } from "../../lib/status";
import {
  comparePersonLines,
  compareStatusByOptionIndex,
  peopleColumn,
  personColumn,
  statusColumn,
  userColumn,
} from "./columns";

const t = ((key: string) => key) as Translator;

describe("compareStatusByOptionIndex", () => {
  const options = [{ value: "blocked" }, { value: "warning" }, { value: "ready" }];

  test("按 options 声明顺序比较", () => {
    expect(compareStatusByOptionIndex("blocked", "ready", options)).toBeLessThan(0);
    expect(compareStatusByOptionIndex("ready", "warning", options)).toBeGreaterThan(0);
    expect(compareStatusByOptionIndex("warning", "warning", options)).toBe(0);
  });

  test("未知值与空值排在已声明取值之后", () => {
    expect(compareStatusByOptionIndex("unknown", "ready", options)).toBeGreaterThan(0);
    expect(compareStatusByOptionIndex(undefined, "blocked", options)).toBeGreaterThan(0);
    expect(compareStatusByOptionIndex("", "warning", options)).toBeGreaterThan(0);
    expect(compareStatusByOptionIndex("unknown", undefined, options)).toBeGreaterThan(0);
  });
});

describe("comparePersonLines", () => {
  test("先比较姓名, 姓名相同再比较次行, 都走 zh-Hans-CN", () => {
    expect(comparePersonLines({ name: "李四", secondary: "A" }, { name: "张三", secondary: "A" })).toBeLessThan(0);
    expect(
      comparePersonLines({ name: "张三", secondary: "安环部" }, { name: "张三", secondary: "财务部" }),
    ).toBeLessThan(0);
    expect(comparePersonLines({ name: "张三", secondary: "安环部" }, { name: "张三", secondary: "安环部" })).toBe(0);
  });
});

describe("列预设 sorter", () => {
  test("statusColumn({ sorter: true }) 比较函数按 options 顺序", () => {
    const column = statusColumn<{ status: string }>({
      key: "status",
      title: "状态",
      sorter: true,
      options: [
        { value: "blocked", label: "阻塞" },
        { value: "ready", label: "就绪" },
      ],
    });
    expect(typeof column.sorter).toBe("function");
    if (typeof column.sorter !== "function") {
      return;
    }
    expect(column.sorter({ status: "blocked" }, { status: "ready" })).toBeLessThan(0);
    expect(column.sorter({ status: "unknown" }, { status: "ready" })).toBeGreaterThan(0);
  });

  test("userColumn({ sorter: true }) 先姓名后次行", () => {
    const column = userColumn<{ name: string; id: string }>({
      key: "user",
      getName: (row) => row.name,
      getUserId: (row) => row.id,
      sorter: true,
    });
    expect(typeof column.sorter).toBe("function");
    if (typeof column.sorter !== "function") {
      return;
    }
    expect(column.sorter({ name: "李四", id: "b" }, { name: "张三", id: "a" })).toBeLessThan(0);
    expect(column.sorter({ name: "张三", id: "a" }, { name: "张三", id: "b" })).toBeLessThan(0);
  });

  test("personColumn({ sorter: true }) 把部门路径当作次行", () => {
    const column = personColumn<{ name: string; user_id: string; department: string }>({
      t,
      getName: (row) => row.name,
      getUserId: (row) => row.user_id,
      getDepartment: (row) => row.department,
      sorter: true,
    });
    expect(typeof column.sorter).toBe("function");
    if (typeof column.sorter !== "function") {
      return;
    }
    expect(
      column.sorter(
        { name: "张三", user_id: "u1", department: "安环部" },
        { name: "张三", user_id: "u2", department: "财务部" },
      ),
    ).toBeLessThan(0);
  });

  test("peopleColumn({ sorter: true }) 按堆叠顺序逐人比较", () => {
    const li: PersonRef = { user_id: "u1", name: "李四", department: "安环部", account_kind: "directory" };
    const zhang: PersonRef = { user_id: "u2", name: "张三", department: "安环部", account_kind: "directory" };
    const column = peopleColumn<{ owners: PersonRef[] }>({
      t,
      getPeople: (row) => row.owners,
      sorter: true,
    });
    expect(typeof column.sorter).toBe("function");
    if (typeof column.sorter !== "function") {
      return;
    }
    expect(column.sorter({ owners: [li] }, { owners: [zhang] })).toBeLessThan(0);
  });
});
