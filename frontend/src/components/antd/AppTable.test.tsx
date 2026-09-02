import { theme } from "antd";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { useState } from "react";
import { describe, expect, test, vi } from "vitest";

import { I18nProvider } from "../../i18n/I18nProvider";
import { AppConfigProvider } from "./AppConfigProvider";
import {
  APP_TABLE_PAGINATION_CLASS,
  AppTable,
  dateRangeFilter,
  orderingSerializer,
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
import {
  actionsColumn,
  dateTimeColumn,
  serverColumn,
  serverSortColumn,
  statusColumn,
  textColumn,
  userColumn,
} from "./columns";
import { ANTD_TEST_TIMEOUT_MS, columnSortOrder, openHeaderFilter, renderWithAntd, sortByColumn } from "./testing";
import { APP_ANTD_THEME, ROW_HOVER_BG } from "./theme";

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

/**
 * AppTable 的两条布局约定(单行分页、视觉隐藏的 caption)只能由真实 CSS 表达:
 * antd 的样式是 CSS-in-JS, 优先级高于 Tailwind 工具类, 主题 token 里也没有
 * flex-wrap 这一项。样式表本身不参与打包进 jsdom, 因此用例把它读进来挂上,
 * 再用 getComputedStyle 断言 —— 这样断的是「规则真的命中了这个元素」,
 * 而不是「代码里写了一个 class 名」。
 */
const APP_TABLE_CSS = readFileSync(resolve(process.cwd(), "src/styles/features/app-table.css"), "utf8");

function installAppTableStylesheet(): HTMLStyleElement {
  const style = document.createElement("style");
  style.dataset.testStylesheet = "app-table";
  style.textContent = APP_TABLE_CSS;
  document.head.append(style);
  return style;
}

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

/**
 * 表头里的列标题。
 *
 * 开了横向滚动(AppTable 恒设 `scroll.x`)的表格, rc-table 会在 tbody 里再渲染一行
 * `tr.ant-table-measure-row` 量列宽, 里面是整份表头的副本(`aria-hidden`, 但
 * `getByText` 照样能找到), 于是同一个列名在 DOM 里出现两次。
 * 要点真正的表头就必须限定在 thead 内。
 */
function columnHeader(title: string): HTMLElement {
  return within(document.querySelector("thead.ant-table-thead") as HTMLElement).getByText(title);
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

  test("分页条被钉成单行: flex-wrap 为 nowrap, 放不下时分页条自己横向滚动", () => {
    // antd 给 .ant-pagination 写死 flex-wrap: wrap, 窄容器下「共 x 条 / 页码 / 每页条数」
    // 会折成两三行。AppTable 统一挂 APP_TABLE_PAGINATION_CLASS, 样式表把它改回 nowrap。
    const style = installAppTableStylesheet();
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    const pagination = document.querySelector("ul.ant-pagination") as HTMLElement;
    expect(pagination.classList.contains(APP_TABLE_PAGINATION_CLASS)).toBe(true);

    const computed = window.getComputedStyle(pagination);
    expect(computed.flexWrap).toBe("nowrap");
    // 换行没有变成「被挤扁」: 放不下时由分页条自己横向滚动。
    expect(computed.overflowX).toBe("auto");

    // 三块内容仍在同一个 ul 里, 而且各自 flex: none, 不会被压成两行字。
    const total = pagination.querySelector(".ant-pagination-total-text") as HTMLElement;
    const options = pagination.querySelector(".ant-pagination-options") as HTMLElement;
    const pager = pagination.querySelector(".ant-pagination-item-1") as HTMLElement;
    expect(total).not.toBeNull();
    expect(options).not.toBeNull();
    expect(pager).not.toBeNull();
    for (const node of [total, options, pager]) {
      expect(window.getComputedStyle(node).whiteSpace).toBe("nowrap");
    }

    style.remove();
  });

  test("ariaLabel 渲染成视觉隐藏的 <caption>, 成为表格的可及名称", () => {
    const style = installAppTableStylesheet();
    renderTable(<AppTable<Row> ariaLabel="我的授权列表" columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    // <caption> 是 HTML 给表格命名的原生方式, 直接就是 role="table" 的可及名称。
    expect(screen.getByRole("table", { name: "我的授权列表" })).toBeInTheDocument();

    const caption = document.querySelector("caption.ant-table-caption") as HTMLElement;
    expect(caption).not.toBeNull();
    // 必须是「视觉隐藏」而不是 display:none —— 后者会把名字一起从无障碍树摘掉。
    const computed = window.getComputedStyle(caption);
    expect(computed.display).not.toBe("none");
    expect(computed.visibility).not.toBe("hidden");
    expect(computed.position).toBe("absolute");
    expect(computed.width).toBe("1px");

    style.remove();
  });

  test("不传 ariaLabel 时不渲染 caption", () => {
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);

    expect(document.querySelector("caption")).toBeNull();
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

    await user.click(columnHeader("Name"));

    await waitFor(() => expect(bodyRowNames()[0]).toBe("Alpha 1"));
    expect(document.querySelector("th.ant-table-column-sort")).not.toBeNull();
  });

  test("空数据渲染 EmptyState", () => {
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={[]} rowKey="id" />);

    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });

  test("空表让 minWidth 让位给 scroll.x=true: 保留滚动容器, 但表格不再被撑宽到 minWidth", () => {
    // 空态框由 antd 包在 `.ant-table-expanded-row-fixed` 里, 宽度写死成「容器宽度」并
    // sticky 在可视区左侧。表格一旦被 minWidth 撑得比容器宽, 空态框就和表头不同宽:
    // 一滚表头整排移动、空态框纹丝不动。空表没有行内容要靠 minWidth 保住列宽,
    // 因此这里把宽度交回布局(x: true), 表头与空态框天然同宽。
    const { unmount } = renderTable(<AppTable<Row> columns={COLUMNS} dataSource={[]} minWidth={900} rowKey="id" />);
    const emptyStyle = document.querySelector(".ant-table-content table")?.getAttribute("style");
    expect(emptyStyle).not.toContain("900px");
    expect(emptyStyle).toContain("width: auto");
    // 滚动容器仍在: 列宽之和放不下时溢出还是得由表格自己吸收, 不能撑出整页横向滚动条。
    expect(document.querySelector(".ant-table-scroll-horizontal")).not.toBeNull();
    expect(document.querySelector(".ant-table-content")).toHaveStyle({ overflowX: "auto" });
    unmount();

    // 有行数据时 minWidth 照旧生效。
    renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} minWidth={900} rowKey="id" />);
    expect(document.querySelector(".ant-table-content table")?.getAttribute("style")).toContain("width: 900px");
  });

  test("scroll.x 恒有值: 不传 minWidth 回落 max-content, 传了就是像素数", () => {
    // 缺省也必须有横向滚动容器: 没有 scroll.x 的表格一旦超宽会把整页撑出横向滚动条,
    // 而且 fixed 布局下没有剩余宽度时无宽度列会被压到 0px。
    const { unmount } = renderTable(<AppTable<Row> columns={COLUMNS} dataSource={ROWS} rowKey="id" />);
    expect(document.querySelector(".ant-table-scroll-horizontal")).not.toBeNull();
    expect(document.querySelector(".ant-table-content")).toHaveStyle({ overflowX: "auto" });
    const defaultStyle = document.querySelector(".ant-table-content table")?.getAttribute("style");
    expect(defaultStyle).toContain("width: max-content");
    // 宽屏下仍然铺满容器。
    expect(defaultStyle).toContain("min-width: 100%");
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

    await user.click(columnHeader("Name"));
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, ordering: "name" }));

    await user.click(columnHeader("Name"));
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, ordering: "-name" }));
  });
});

describe("orderingSerializer + serverSortColumn", () => {
  test("列 key 按映射表翻成后端字段名, 降序加 - 前缀; 表里没有的列不产生参数", () => {
    const serialize = orderingSerializer({ submitted_at: "created_at", app: "app_key" });

    expect(serialize({ field: "submitted_at", order: "ascend" })).toEqual({ ordering: "created_at" });
    expect(serialize({ field: "submitted_at", order: "descend" })).toEqual({ ordering: "-created_at" });
    expect(serialize({ field: "app", order: "ascend" })).toEqual({ ordering: "app_key" });
    // 后端排不了的列(页面也不该给它 sorter): 不带排序参数, 由后端用默认序。
    expect(serialize({ field: "owners", order: "ascend" })).toEqual({});
    // 参数名可改, 拼法只此一份。
    expect(orderingSerializer({ name: "name" }, "sort")({ field: "name", order: "descend" })).toEqual({
      sort: "-name",
    });
  });

  test("serverSortColumn 去掉客户端比较函数, 指示器由查询状态受控", async () => {
    const user = userEvent.setup({ delay: null });
    const seen: Record<string, unknown>[] = [];

    function SortedTable() {
      const serverTable = useServerTable<Row>({
        total: 42,
        defaultSort: { field: "updated_at", order: "descend" },
        serializeSort: orderingSerializer({ name: "name", updated_at: "updated_at" }),
      });
      seen.push(serverTable.params);
      // dateTimeColumn 默认自带时间戳比较函数, serverSortColumn 必须把它换成服务端排序。
      const columns: ColumnsType<Row> = [
        serverSortColumn(textColumn<Row>({ key: "name", title: "Name", sorter: true }), serverTable.query),
        serverSortColumn(dateTimeColumn<Row>({ key: "updated_at", title: "Updated" }), serverTable.query),
      ];
      expect(columns.every((column) => (column as ColumnType<Row>).sorter === true)).toBe(true);
      return (
        <AppTable<Row>
          {...serverTable.tableProps}
          columns={columns}
          dataSource={ROWS.slice(0, 10)}
          rowKey="id"
        />
      );
    }

    renderWithAntd(<SortedTable />);

    // defaultSort 直接进请求参数, 表头也立刻带上指示器。
    expect(seen[0]).toEqual({ page: 1, page_size: 10, ordering: "-updated_at" });
    expect(columnSortOrder("Updated")).toBe("descend");

    await sortByColumn(user, "Name");
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, ordering: "name" }));
    // 另一列排序时本列必须显式回到未排序, 否则会同时亮两个指示器。
    expect(columnSortOrder("Name")).toBe("ascend");
    expect(columnSortOrder("Updated")).toBeNull();

    await sortByColumn(user, "Name");
    await waitFor(() => expect(seen.at(-1)).toEqual({ page: 1, page_size: 10, ordering: "-name" }));
    expect(columnSortOrder("Name")).toBe("descend");
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

describe("固定列的行态底色", () => {
  const ANTD_TOKENS = theme.getDesignToken(APP_ANTD_THEME);
  /** app-table.css 里三条固定单元格规则各自的判别式(选择器里出现哪些行态类)。 */
  const FIXED_CELL_STATES = {
    hover: (selector: string) =>
      selector.includes(".ant-table-cell-row-hover") && !selector.includes(".ant-table-row-selected"),
    selected: (selector: string) =>
      selector.includes(".ant-table-row-selected") && !selector.includes(".ant-table-cell-row-hover"),
    selectedHover: (selector: string) =>
      selector.includes(".ant-table-row-selected") && selector.includes(".ant-table-cell-row-hover"),
  } as const;

  const FIXED_COLUMNS: ColumnsType<Row> = [
    textColumn<Row>({ key: "name", title: "Name" }),
    actionsColumn<Row>({ render: (row) => <button type="button">edit {row.id}</button> }),
  ];

  function fixedCellRule(state: keyof typeof FIXED_CELL_STATES): { selectors: string[]; background: string } {
    // 只解析 background 一项: 用例断的就是「这三种行态的固定单元格底色是什么」。
    const source = APP_TABLE_CSS.replace(/\/\*[\s\S]*?\*\//g, "");
    const rules = [...source.matchAll(/([^{}]+)\{([^}]*)\}/g)]
      .map(([, selectorList, body]) => ({
        selectors: (selectorList ?? "").split(",").map((selector) => selector.trim()).filter(Boolean),
        background: (/background:\s*([^;]+);/.exec(body ?? "")?.[1] ?? "").trim(),
      }))
      .filter((rule) => rule.selectors.every((selector) => selector.includes(".ant-table-cell-fix-")));
    const matched = rules.filter((rule) => rule.selectors.every(FIXED_CELL_STATES[state]));
    expect(matched).toHaveLength(1);
    return matched[0] as { selectors: string[]; background: string };
  }

  /** 半透明底色画到不透明背景上的结果; 浏览器就是这么合成行悬停色的。 */
  function compositeToHex(overlay: string, base: string): string {
    const overlayChannels = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)/.exec(overlay);
    if (!overlayChannels) {
      throw new Error(`不是 rgba() 色值: ${overlay}`);
    }
    const alpha = Number(overlayChannels[4]);
    const baseChannels = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(base);
    if (!baseChannels) {
      throw new Error(`不是 #rrggbb 色值: ${base}`);
    }
    const channels = [1, 2, 3].map((index) => {
      const overlayChannel = Number(overlayChannels[index]);
      const baseChannel = Number.parseInt(baseChannels[index] ?? "", 16);
      return Math.round(overlayChannel * alpha + baseChannel * (1 - alpha));
    });
    return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
  }

  test("样式表给三种行态都写了不透明底色, 色值与 theme.ts / antd 令牌一致", () => {
    // 半透明的行悬停色是 bug 的来源, 也是不透明色的唯一出处。
    expect(APP_ANTD_THEME.components?.Table?.rowHoverBg).toBe(ROW_HOVER_BG);

    const expected = {
      hover: compositeToHex(ROW_HOVER_BG, ANTD_TOKENS.colorBgContainer),
      selected: ANTD_TOKENS.controlItemBgActive,
      selectedHover: ANTD_TOKENS.controlItemBgActiveHover,
    } as const;

    for (const state of ["hover", "selected", "selectedHover"] as const) {
      const rule = fixedCellRule(state);
      // 现在只有操作列(fix-right)固定, 但左固定列是同一个 bug, 必须一起钉住。
      expect(rule.selectors.some((selector) => selector.includes(".ant-table-cell-fix-left"))).toBe(true);
      expect(rule.selectors.some((selector) => selector.includes(".ant-table-cell-fix-right"))).toBe(true);
      // 不透明: 只要带 alpha, 从固定列底下滚过去的单元格就会透上来。
      expect(rule.background).toMatch(/^#[0-9a-f]{6}$/i);
      expect(rule.background.toLowerCase()).toBe(expected[state].toLowerCase());
    }
  });

  test("hover 与选中态下, 固定列单元格算出来的底色确实是不透明色", () => {
    const style = installAppTableStylesheet();
    renderWithAntd(
      <AppTable<Row>
        columns={FIXED_COLUMNS}
        dataSource={ROWS.slice(0, 3)}
        minWidth={900}
        pagination={false}
        rowKey="id"
        rowSelection={{ selectedRowKeys: ["row-2"] }}
      />,
    );

    const rows = [...document.querySelectorAll(".ant-table-tbody > tr.ant-table-row")];
    const fixedCell = (row: Element) => row.querySelector("td.ant-table-cell-fix-right") as HTMLElement;
    const background = (cell: HTMLElement) => window.getComputedStyle(cell).backgroundColor;

    // rc-table 的行 hover 是 JS 驱动的: mouseenter 给整行单元格挂 .ant-table-cell-row-hover。
    fireEvent.mouseEnter(rows[0]?.querySelector("td") as HTMLElement);
    expect(fixedCell(rows[0] as Element).classList.contains("ant-table-cell-row-hover")).toBe(true);
    expect(background(fixedCell(rows[0] as Element))).toBe("rgb(244, 247, 254)");

    // 选中行(未悬停)与「选中 + 悬停」各走各的底色, hover 规则不能把选中色盖掉。
    expect(rows[1]?.classList.contains("ant-table-row-selected")).toBe(true);
    expect(background(fixedCell(rows[1] as Element))).toBe("rgb(240, 247, 255)");

    fireEvent.mouseEnter(rows[1]?.querySelector("td") as HTMLElement);
    expect(background(fixedCell(rows[1] as Element))).toBe("rgb(204, 227, 255)");

    style.remove();
  });
});
