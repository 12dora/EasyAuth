import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { AppConfigProvider } from "./AppConfigProvider";
import { AppTable, enumFilter, textFilter, useServerTable, type ColumnsType } from "./AppTable";
import { actionsColumn, dateTimeColumn, statusColumn, textColumn, userColumn } from "./columns";

// antd Table 在 jsdom 里每次筛选/排序都要重建整棵表格, 比自研原语慢得多,
// 默认 5s 不够; 这里只放宽本文件的用例超时。
vi.setConfig({ testTimeout: 20000 });

interface Row {
  id: string;
  name: string;
  status: string;
  updated_at: string;
}

const ROWS: Row[] = Array.from({ length: 12 }, (_, index) => ({
  id: `row-${index + 1}`,
  name: index % 2 === 0 ? `Alpha ${index + 1}` : `Beta ${index + 1}`,
  status: index % 3 === 0 ? "active" : "blocked",
  updated_at: `2026-01-${String(index + 1).padStart(2, "0")}T08:00:00Z`,
}));

const COLUMNS: ColumnsType<Row> = [
  { title: "Name", dataIndex: "name", key: "name", sorter: (a, b) => a.name.localeCompare(b.name), ...textFilter<Row>("name") },
  {
    title: "Status",
    dataIndex: "status",
    key: "status",
    ...enumFilter<Row>("status", [
      { label: "Active", value: "active" },
      { label: "Blocked", value: "blocked" },
    ]),
  },
];

function renderTable(ui: React.ReactElement) {
  return render(
    <I18nProvider>
      <AppConfigProvider>{ui}</AppConfigProvider>
    </I18nProvider>,
  );
}

function bodyRowNames(): string[] {
  const rows = document.querySelectorAll(".ant-table-tbody tr.ant-table-row");
  return [...rows].map((row) => row.querySelector("td")?.textContent ?? "");
}

describe("AppTable 客户端模式", () => {
  test("默认每页 10 条并渲染 showTotal 区间文案", () => {
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    expect(bodyRowNames()).toHaveLength(10);
    expect(screen.getByText("第 1-10 条 / 共 12 条")).toBeInTheDocument();
  });

  test("分页控件全部渲染在同一行容器里", () => {
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    const pagination = document.querySelector("ul.ant-pagination");
    expect(pagination).not.toBeNull();
    // 区间文案、页码按钮、每页条数 Select 必须同属一个 ul, 不能拆成两行。
    expect(pagination?.querySelector(".ant-pagination-total-text")).not.toBeNull();
    expect(pagination?.querySelector(".ant-pagination-item-1")).not.toBeNull();
    expect(pagination?.querySelector(".ant-pagination-options")).not.toBeNull();
    // size="small" 让页码按钮与 Select 同取 controlHeightSM(28px)。
    expect(pagination?.classList.contains("ant-pagination-mini")).toBe(true);
    expect(pagination?.querySelector(".ant-pagination-options .ant-select-sm")).not.toBeNull();
    // 位置约定 bottomRight: antd 5 用 ant-pagination-end 表达右对齐。
    expect(pagination?.classList.contains("ant-pagination-end")).toBe(true);
    expect(document.querySelector(".ant-table-pagination")).not.toBeNull();
  });

  test("切换每页条数后展示全部数据", async () => {
    const user = userEvent.setup({ delay: null });
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    await user.click(document.querySelector(".ant-pagination-options .ant-select-selector") as HTMLElement);
    await user.click(await screen.findByTitle("20 条/页"));

    await waitFor(() => expect(bodyRowNames()).toHaveLength(12));
    expect(screen.getByText("第 1-12 条 / 共 12 条")).toBeInTheDocument();
  });

  test("文本筛选按子串匹配, 重置后恢复全部数据", async () => {
    const user = userEvent.setup({ delay: null });
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    await user.click(document.querySelectorAll(".ant-table-filter-trigger")[0] as HTMLElement);
    await user.type(await screen.findByLabelText("筛选关键字"), "Beta");
    await user.click(screen.getByRole("button", { name: "确定" }));

    await waitFor(() => expect(bodyRowNames().length).toBe(6));
    expect(bodyRowNames().every((name) => name.startsWith("Beta"))).toBe(true);

    await user.click(document.querySelectorAll(".ant-table-filter-trigger")[0] as HTMLElement);
    await user.click(await screen.findByRole("button", { name: "重置" }));

    await waitFor(() => expect(bodyRowNames()).toHaveLength(10));
  });

  test("枚举筛选走 antd 内建复选下拉", async () => {
    const user = userEvent.setup({ delay: null });
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    await user.click(document.querySelectorAll(".ant-table-filter-trigger")[1] as HTMLElement);
    const dropdown = (await screen.findByText("Active")).closest(".ant-table-filter-dropdown") as HTMLElement;
    await user.click(within(dropdown).getByText("Active"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(bodyRowNames()).toHaveLength(4));
  });

  test("排序按列比较函数生效", async () => {
    const user = userEvent.setup({ delay: null });
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    await user.click(screen.getByText("Name"));

    await waitFor(() => expect(bodyRowNames()[0]).toBe("Alpha 1"));
    expect(document.querySelector("th.ant-table-column-sort")).not.toBeNull();
  });

  test("空数据渲染 EmptyState", () => {
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={[]} rowKey="id" />);

    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });

  test("传 minWidth 才写入 scroll.x", () => {
    const { unmount } = renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);
    expect(document.querySelector(".ant-table-scroll-horizontal")).toBeNull();
    expect(document.querySelector(".ant-table-wrapper")?.classList.contains("w-full")).toBe(true);
    unmount();

    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} minWidth={900} rowKey="id" />);
    expect(document.querySelector(".ant-table-scroll-horizontal")).not.toBeNull();
    expect(document.querySelector(".ant-table-content table")?.getAttribute("style")).toContain("width: 900px");
  });
});

describe("AppTable 语言切换", () => {
  test("en 下 showTotal 与 antd 内建分页文案都走英文", async () => {
    window.localStorage.setItem("easyauth.locale", "en");
    const user = userEvent.setup({ delay: null });
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    expect(screen.getByText("1-10 of 12")).toBeInTheDocument();

    await user.click(document.querySelector(".ant-pagination-options .ant-select-selector") as HTMLElement);
    // antd/locale/en_US 的 items_per_page = "/ page"。
    expect(await screen.findByTitle("20 / page")).toBeInTheDocument();
  });
});

describe("列预设", () => {
  const PRESET_COLUMNS: ColumnsType<Row> = [
    userColumn<Row>({ key: "name", getName: (row) => row.name, getUserId: (row) => row.id }),
    statusColumn<Row>({
      key: "status",
      title: "Status",
      options: [
        { label: "Active", value: "active", tone: "evergreen" },
        { label: "Blocked", value: "blocked", tone: "signal" },
      ],
    }),
    dateTimeColumn<Row>({ key: "updated_at", title: "Updated" }),
    textColumn<Row>({ key: "id", title: "ID", mono: true }),
    actionsColumn<Row>({ render: (row) => <button type="button">edit {row.id}</button> }),
  ];

  test("状态列渲染 Badge, 时间列跟随语言, 操作列固定右侧", () => {
    renderTable(
      <AppTable<Row> columns={PRESET_COLUMNS} dataSource={ROWS.slice(0, 1)} minWidth={900} pagination={false} rowKey="id" />,
    );

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("2026/01/01 16:00")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "edit row-1" })).toBeInTheDocument();
    expect(document.querySelector("th.ant-table-cell-fix-right")).not.toBeNull();
    // 固定列的标题会额外出现在 antd 的测量行里, 因此用 getAllByText。
    expect(screen.getAllByText("操作").length).toBeGreaterThan(0);
    expect(screen.getAllByText("用户").length).toBeGreaterThan(0);
  });

  test("状态列自带枚举筛选", async () => {
    const user = userEvent.setup({ delay: null });
    renderTable(<AppTable<Row> columns={PRESET_COLUMNS} dataSource={ROWS} minWidth={900} rowKey="id" />);

    await user.click(document.querySelectorAll(".ant-table-filter-trigger")[0] as HTMLElement);
    // Badge 单元格里也有 "Blocked", 必须把查询限定在筛选下拉内。
    const dropdown = await waitFor(() => {
      const node = document.querySelector(".ant-table-filter-dropdown");
      expect(node).not.toBeNull();
      return node as HTMLElement;
    });
    await user.click(within(dropdown).getByText("Blocked"));
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(bodyRowNames()).toHaveLength(8));
  });
});

describe("useServerTable", () => {
  function ServerTable({ onParams }: { onParams: (params: Record<string, unknown>) => void }) {
    const serverTable = useServerTable<Row>({
      total: 42,
      filterParams: { status: "status", name: "q" },
    });
    onParams(serverTable.params);
    return (
      <AppTable<Row>
        {...serverTable.tableProps}
        columns={COLUMNS}
        dataSource={ROWS.slice(0, 10)}
        rowKey="id"
      />
    );
  }

  test("初始参数为 page/page_size, 翻页与筛选映射成后端查询参数且筛选回到第 1 页", async () => {
    const user = userEvent.setup({ delay: null });
    const seen: Record<string, unknown>[] = [];
    renderTable(<ServerTable onParams={(params) => seen.push(params)} />);

    expect(seen[0]).toEqual({ page: 1, page_size: 10 });
    expect(screen.getByText("第 1-10 条 / 共 42 条")).toBeInTheDocument();

    await user.click(screen.getByTitle("2"));
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 2, page_size: 10 }));

    await user.click(document.querySelectorAll(".ant-table-filter-trigger")[0] as HTMLElement);
    await user.type(await screen.findByLabelText("筛选关键字"), "alpha");
    await user.click(screen.getByRole("button", { name: "确定" }));

    // 筛选后页码强制回到 1, 并按 filterParams 映射成 q。
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, q: "alpha" }));
  });

  test("排序映射成 DRF 风格的 ordering 参数", async () => {
    const user = userEvent.setup({ delay: null });
    const seen: Record<string, unknown>[] = [];
    renderTable(<ServerTable onParams={(params) => seen.push(params)} />);

    await user.click(screen.getByText("Name"));
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, ordering: "name" }));

    await user.click(screen.getByText("Name"));
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, ordering: "-name" }));
  });
});
