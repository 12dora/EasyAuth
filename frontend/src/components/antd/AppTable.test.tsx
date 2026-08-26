import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { AppConfigProvider } from "./AppConfigProvider";
import {
  AppTable,
  dateRangeFilter,
  decodeDateRange,
  encodeDateRange,
  enumFilter,
  serverTableQuery,
  tablePropsWithTotal,
  textFilter,
  useServerTable,
  type ColumnsType,
  type ColumnType,
  type FilterDropdownProps,
  type FilterValue,
  type SorterResult,
  type TableCurrentDataSource,
} from "./AppTable";
import { actionsColumn, dateTimeColumn, serverColumn, statusColumn, textColumn, userColumn } from "./columns";
import { ANTD_TEST_TIMEOUT_MS, openHeaderFilter, renderWithAntd } from "./testing";

// antd Table 在 jsdom 里每次筛选/排序都要重建整棵表格, 比自研原语慢得多,
// 默认 5s 不够; 这里只放宽本文件的用例超时。
vi.setConfig({ testTimeout: ANTD_TEST_TIMEOUT_MS });

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

describe("useServerTable 总条数回填", () => {
  function LateTotalTable({ totals }: { totals: (number | undefined)[] }) {
    const [step, setStep] = useState(0);
    const serverTable = useServerTable<Row>();
    // 页面的常规写法: 拿到响应后在渲染期回填, 等值短路保证不会自我循环。
    serverTable.setTotal(totals[step]);
    return (
      <>
        <button type="button" onClick={() => setStep((current) => current + 1)}>
          next
        </button>
        <AppTable<Row> {...serverTable.tableProps} columns={COLUMNS} dataSource={ROWS.slice(0, 10)} rowKey="id" />
      </>
    );
  }

  test("setTotal 把总条数补进 tableProps, 请求未回来时先按 0 渲染", async () => {
    const user = userEvent.setup({ delay: null });
    renderWithAntd(<LateTotalTable totals={[undefined, 42, undefined, 7]} />);

    // 第一帧还没有总数: total 为 0 时 antd 回落到当前页的行数, 不报错也不渲染循环。
    expect(screen.getByText("第 1-10 条 / 共 10 条")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "next" }));
    await waitFor(() => expect(screen.getByText("第 1-10 条 / 共 42 条")).toBeInTheDocument());

    // undefined 表示「这次还不知道」: 保留上一次的总数, 分页条不闪 0。
    await user.click(screen.getByRole("button", { name: "next" }));
    expect(screen.getByText("第 1-10 条 / 共 42 条")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "next" }));
    await waitFor(() => expect(screen.getByText("第 1-7 条 / 共 7 条")).toBeInTheDocument());
  });

  test("老的 total 选项继续生效并优先于 setTotal", () => {
    function OptionTotalTable() {
      const serverTable = useServerTable<Row>({ total: 42 });
      serverTable.setTotal(9);
      expect(serverTable.total).toBe(42);
      return <AppTable<Row> {...serverTable.tableProps} columns={COLUMNS} dataSource={ROWS.slice(0, 10)} rowKey="id" />;
    }

    renderWithAntd(<OptionTotalTable />);

    expect(screen.getByText("第 1-10 条 / 共 42 条")).toBeInTheDocument();
  });

  test("tablePropsWithTotal 是只有 tableProps 时的纯函数版本", () => {
    const onChange = vi.fn();
    const merged = tablePropsWithTotal<Row>({ pagination: { current: 2, pageSize: 10 }, onChange }, 42);

    expect(merged.pagination).toEqual({ current: 2, pageSize: 10, total: 42 });
    expect(merged.onChange).toBe(onChange);
    // 关掉分页的表格不会被塞回一个分页配置。
    expect(tablePropsWithTotal<Row>({ pagination: false }, 42).pagination).toBe(false);
  });
});

describe("serverTableQuery", () => {
  test("空值不进查询串, 数组按同名多值展开, 键顺序沿用参数对象", () => {
    expect(serverTableQuery({ page: 1, page_size: 10, status: "active" })).toBe("page=1&page_size=10&status=active");
    expect(serverTableQuery({ page: 1, status: "" })).toBe("page=1");
    expect(serverTableQuery({ page: 1, status: ["active", "", "blocked"] })).toBe(
      "page=1&status=active&status=blocked",
    );
    expect(serverTableQuery({ page: 1 }, { app_key: "demo", empty: "" })).toBe("page=1&app_key=demo");
  });
});

describe("serverColumn", () => {
  interface AuditRow {
    id: string;
    // 审计的 app_key 藏在 metadata 里, 且不是每行都有: 后端按库字段筛得到的行,
    // 客户端按 metadata 再筛一遍就会莫名其妙地掉。
    metadata: { app?: string };
  }

  const AUDIT_ROWS: AuditRow[] = [
    { id: "a-1", metadata: { app: "demo" } },
    { id: "a-2", metadata: {} },
  ];

  const appColumn = () =>
    textColumn<AuditRow>({
      key: "app",
      title: "应用",
      getValue: (row) => row.metadata.app,
      filter: true,
    });

  function auditRowCount(): number {
    return document.querySelectorAll(".ant-table-tbody tr.ant-table-row").length;
  }

  test("受控筛选下 antd 依然会跑列自带的 onFilter, 把服务端已筛过的页再筛一遍", () => {
    // 这条用例锁住 serverColumn 存在的理由: 不去掉 onFilter 就是这个结果 ——
    // 后端返回的两行里, metadata 上读不到 app 的那行被客户端静默丢掉。
    renderWithAntd(
      <AppTable<AuditRow>
        columns={[{ ...appColumn(), filteredValue: ["demo"] }]}
        dataSource={AUDIT_ROWS}
        pagination={false}
        rowKey="id"
      />,
    );

    expect(auditRowCount()).toBe(1);
  });

  test("serverColumn 去掉 onFilter 并受控 filteredValue, 整页数据原样保留", () => {
    const column = serverColumn(appColumn(), ["demo"]);

    expect(column.onFilter).toBeUndefined();
    expect(column.filteredValue).toEqual(["demo"]);

    renderWithAntd(<AppTable<AuditRow> columns={[column]} dataSource={AUDIT_ROWS} pagination={false} rowKey="id" />);

    expect(auditRowCount()).toBe(2);
    // 表头筛选图标要处于「已筛选」态, 与 URL 里的参数对得上。
    expect(document.querySelector(".ant-table-filter-trigger.active")).not.toBeNull();
  });

  test("未筛选时 filteredValue 归 null, 空数组同样视为未筛选", () => {
    expect(serverColumn(appColumn()).filteredValue).toBeNull();
    expect(serverColumn(appColumn(), []).filteredValue).toBeNull();
    expect(serverColumn(appColumn(), null).filteredValue).toBeNull();
  });

  test("内建枚举下拉默认单选, multiple: true 时才允许多选", async () => {
    const statusOptions = [
      { label: "Active", value: "active", tone: "evergreen" as const },
      { label: "Blocked", value: "blocked", tone: "signal" as const },
    ];
    const single = serverColumn(statusColumn<Row>({ key: "status", title: "状态", options: statusOptions }));
    const multiple = serverColumn(
      statusColumn<Row>({ key: "status", title: "状态", options: statusOptions }),
      ["active"],
      { multiple: true },
    );

    expect(single.filterMultiple).toBe(false);
    expect(multiple.filterMultiple).toBe(true);
    // 自定义下拉(文本/时间范围)没有内建 filters, 不该被塞 filterMultiple。
    expect("filterMultiple" in serverColumn(appColumn())).toBe(false);

    const user = userEvent.setup({ delay: null });
    renderWithAntd(<AppTable<Row> columns={[single]} dataSource={ROWS} pagination={false} rowKey="id" />);

    const dropdown = await openHeaderFilter(user, "状态");
    expect(dropdown.querySelectorAll("input[type='radio']").length).toBe(2);
    expect(dropdown.querySelectorAll("input[type='checkbox']").length).toBe(0);
  });
});

describe("dateRangeFilter", () => {
  test("起止编解码与后端参数名", () => {
    const range = dateRangeFilter<Row>("submitted");

    expect(range.encode({ from: "", to: "" })).toEqual([]);
    expect(range.encode({ from: "2026-01-01T00:00", to: "" })).toEqual(["2026-01-01T00:00~"]);
    expect(range.decode(["2026-01-01T00:00~2026-02-01T00:00"])).toEqual({
      from: "2026-01-01T00:00",
      to: "2026-02-01T00:00",
    });
    expect(range.decode(undefined)).toEqual({ from: "", to: "" });
    expect(range.toParams("2026-01-01T00:00", "2026-02-01T00:00")).toEqual({
      submitted_from: "2026-01-01T00:00",
      submitted_to: "2026-02-01T00:00",
    });
    // 只填一端时另一端不进参数。
    expect(range.toParams("", "2026-02-01T00:00")).toEqual({ submitted_to: "2026-02-01T00:00" });
    // 默认前缀 created, 与独立导出的编解码函数同构。
    expect(dateRangeFilter<Row>().toParams("2026-01-01T00:00", "")).toEqual({ created_from: "2026-01-01T00:00" });
    expect(decodeDateRange(encodeDateRange({ from: "a", to: "b" }))).toEqual({ from: "a", to: "b" });
  });

  test("下拉里两个时间输入 + 确定, 把起止编码进同一个筛选值回传 onChange", async () => {
    const user = userEvent.setup({ delay: null });
    const onChange = vi.fn();
    const column: ColumnType<Row> = {
      ...dateTimeColumn<Row>({ key: "updated_at", title: "时间", sorter: false }),
      ...dateRangeFilter<Row>("created"),
    };

    renderWithAntd(
      <AppTable<Row>
        columns={[column]}
        dataSource={ROWS.slice(0, 2)}
        onChange={onChange}
        pagination={false}
        rowKey="id"
      />,
    );

    const dropdown = await openHeaderFilter(user, "时间");
    // aria-label 默认按 `<paramKey>_from` / `<paramKey>_to` 生成。
    fireEvent.change(within(dropdown).getByLabelText("created_from"), { target: { value: "2026-01-01T00:00" } });
    fireEvent.change(within(dropdown).getByLabelText("created_to"), { target: { value: "2026-02-01T00:00" } });
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const filters = onChange.mock.calls.at(-1)?.[1] as Record<string, FilterValue | null>;
    expect(filters.updated_at).toEqual(["2026-01-01T00:00~2026-02-01T00:00"]);
    expect(decodeDateRange(filters.updated_at)).toEqual({ from: "2026-01-01T00:00", to: "2026-02-01T00:00" });
  });

  test("重置清空两端并回传未筛选", async () => {
    const user = userEvent.setup({ delay: null });
    const onChange = vi.fn();
    const column: ColumnType<Row> = {
      ...dateTimeColumn<Row>({ key: "updated_at", title: "时间", sorter: false }),
      ...dateRangeFilter<Row>("created"),
    };

    renderWithAntd(
      <AppTable<Row>
        columns={[column]}
        dataSource={ROWS.slice(0, 2)}
        onChange={onChange}
        pagination={false}
        rowKey="id"
      />,
    );

    const dropdown = await openHeaderFilter(user, "时间");
    fireEvent.change(within(dropdown).getByLabelText("created_from"), { target: { value: "2026-01-01T00:00" } });
    await user.click(within(dropdown).getByRole("button", { name: "确定" }));
    await waitFor(() => expect(onChange).toHaveBeenCalled());

    const reopened = await openHeaderFilter(user, "时间");
    await user.click(within(reopened).getByRole("button", { name: "重置" }));

    await waitFor(() => {
      const filters = onChange.mock.calls.at(-1)?.[1] as Record<string, FilterValue | null>;
      expect(filters.updated_at ?? null).toBeNull();
    });
  });
});

describe("类型再导出", () => {
  test("页面不用碰 antd/es/table/* 也能写筛选下拉与 onChange 的签名", () => {
    // 这条用例的价值在编译期: 这些注解只要能通过 tsc, 再导出就是可用的。
    const renderDropdown = (props: FilterDropdownProps) => props.selectedKeys.map(String).join(",");
    const handleChange = (
      _pagination: unknown,
      filters: Record<string, FilterValue | null>,
      sorter: SorterResult<Row> | SorterResult<Row>[],
      extra: TableCurrentDataSource<Row>,
    ) => ({
      filters,
      field: Array.isArray(sorter) ? sorter[0]?.columnKey : sorter.columnKey,
      action: extra.action,
    });

    expect(
      renderDropdown({
        prefixCls: "ant-table-filter-dropdown",
        setSelectedKeys: () => undefined,
        selectedKeys: ["a", "b"],
        confirm: () => undefined,
        clearFilters: undefined,
        filters: [],
        visible: true,
        close: () => undefined,
      }),
    ).toBe("a,b");
    expect(
      handleChange(undefined, { status: ["active"] }, { columnKey: "status" }, { currentDataSource: ROWS, action: "filter" }),
    ).toEqual({ filters: { status: ["active"] }, field: "status", action: "filter" });
  });
});
