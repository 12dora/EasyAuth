import { Button as AntdButton, Input, Table } from "antd";
import type { TablePaginationConfig, TableProps } from "antd";
import type {
  ColumnGroupType,
  ColumnType,
  ColumnsType,
  FilterDropdownProps,
  FilterValue,
  SorterResult,
  SortOrder,
  TableCurrentDataSource,
} from "antd/es/table/interface";
import { useCallback, useMemo, useState, type Key, type ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import { EmptyState } from "../ui/EmptyState";

export type { ColumnGroupType, ColumnType, ColumnsType, TablePaginationConfig, TableProps };
/**
 * antd 表格的「回调签名」类型。页面写自定义 filterDropdown 或 onChange 时需要它们,
 * 但 `antd/es/table/*` 是内部路径(迁移护栏 FORBIDDEN_ANTD_TABLE_IMPORT 也禁止页面直接引),
 * 所以统一从这里再导出。
 */
export type { FilterDropdownProps, FilterValue, SortOrder, SorterResult, TableCurrentDataSource };

/** 分页尺寸选项与默认页长的唯一出处; 页面不要各自再造一套。 */
export const APP_TABLE_PAGE_SIZE_OPTIONS = [10, 20, 50, 100] as const;
export const APP_TABLE_DEFAULT_PAGE_SIZE = 10;

export interface AppTableProps<T> extends Omit<TableProps<T>, "rowKey" | "pagination" | "locale"> {
  /** 必填: 行身份只能来自数据字段, 不允许回落数组下标。 */
  rowKey: NonNullable<TableProps<T>["rowKey"]>;
  /**
   * 传入即开启横向滚动(写入 `scroll.x`)。
   * 列多且宽度不定时传 "max-content"; 需要固定最小宽度时传像素数。
   * 使用 `actionsColumn`(fixed: "right")时必须传, 否则 antd 无法固定列。
   * 不传则完全不设 `scroll.x`, 表格随容器宽度收缩。
   */
  minWidth?: number | "max-content";
  /**
   * 客户端模式: 省略或只覆盖展示项, antd 自己分页/排序/筛选。
   * 服务端模式: 展开 `useServerTable().tableProps`。
   * 传 false 关闭分页。
   * 分页样式由 AppTable 统一决定, 页面只该传 current/pageSize/total。
   */
  pagination?: TablePaginationConfig | false;
  /** 空态标题; 缺省用 i18n 的「暂无数据」。 */
  emptyTitle?: string;
  emptyDescription?: string;
  emptyIcon?: ReactNode;
  emptyAction?: ReactNode;
  /** 需要完全自定义空态时传节点, 会覆盖上面四个字段。 */
  empty?: ReactNode;
}

/**
 * 全站数据表格的唯一入口。所有布局约定都在这里, 页面不再重复:
 * w-full、size="middle"、tableLayout="fixed"、rowKey 必填、
 * 行高(主题 Table token)、空态(复用 EmptyState)、加载态、单行分页。
 *
 * 分页显式写死 size="small": antd 在 size="middle" 的表格下本来也会把分页降为
 * small, 显式写出来是为了让「页码按钮」和「每页条数 Select」同时取
 * controlHeightSM(28px, 等于 Button size="sm" 的 h-7), 不依赖 antd 内部联动。
 */
export function AppTable<T extends object>({
  className,
  empty,
  emptyAction,
  emptyDescription,
  emptyIcon,
  emptyTitle,
  minWidth,
  pagination,
  rowKey,
  scroll,
  size = "middle",
  sticky = false,
  tableLayout = "fixed",
  ...rest
}: AppTableProps<T>) {
  const { t } = useI18n();

  const mergedPagination = useMemo<TablePaginationConfig | false>(() => {
    if (pagination === false) {
      return false;
    }
    return {
      defaultPageSize: APP_TABLE_DEFAULT_PAGE_SIZE,
      pageSizeOptions: [...APP_TABLE_PAGE_SIZE_OPTIONS],
      position: ["bottomRight"],
      showSizeChanger: true,
      size: "small",
      showTotal: (total, range) => t("table.pagination.total", { start: range[0], end: range[1], total }),
      ...pagination,
    };
  }, [pagination, t]);

  const mergedScroll = useMemo(() => {
    if (minWidth === undefined) {
      return scroll;
    }
    return { ...scroll, x: minWidth };
  }, [minWidth, scroll]);

  const locale = useMemo(
    () => ({
      emptyText: empty ?? (
        <EmptyState
          action={emptyAction}
          description={emptyDescription}
          icon={emptyIcon}
          title={emptyTitle ?? t("table.empty.title")}
        />
      ),
    }),
    [empty, emptyAction, emptyDescription, emptyIcon, emptyTitle, t],
  );

  return (
    <Table<T>
      className={cn("w-full", className)}
      locale={locale}
      pagination={mergedPagination}
      rowKey={rowKey}
      scroll={mergedScroll}
      size={size}
      sticky={sticky}
      tableLayout={tableLayout}
      {...rest}
    />
  );
}

/* ------------------------------------------------------------------ */
/* 服务端分页 / 排序 / 筛选                                             */
/* ------------------------------------------------------------------ */

export interface ServerTableQuery {
  /** 1 基页码。 */
  page: number;
  pageSize: number;
  /** 当前排序列的 `key`(未设 key 时为 dataIndex); 无排序为 undefined。 */
  sortField?: string;
  sortOrder?: "ascend" | "descend";
  /** 列 key -> 选中值; 文本筛选为单元素数组。无筛选的列不出现。 */
  filters: Record<string, string[]>;
}

/** 列 key -> 后端查询参数名, 或更精细的配置。 */
export type ServerFilterParamMap = Record<string, string | ServerFilterParam>;

export interface ServerFilterParam {
  /** 后端查询参数名, 例如 "app_key"。 */
  param: string;
  /** true 时保留全部选中值(数组); 默认只取第一个值。 */
  multiple?: boolean;
  /** 自定义序列化; 返回 undefined 表示不带这个参数。 */
  serialize?: (values: string[]) => string | string[] | undefined;
}

/** useServerTable 产出的、可直接拼进请求的查询参数。 */
export type ServerTableParams = Record<string, string | string[] | number>;

export interface UseServerTableOptions {
  /**
   * 后端返回的总条数; 缺省按 0 处理。
   *
   * 只有「建 hook 时就已知总数」的场景(例如总数来自另一个已完成的查询)才传这个。
   * 常规服务端分页里总数来自 `params` 发出的那次请求, 声明顺序上拿不到 ——
   * 那种情况改用 `setTotal(n)` 在拿到响应后回填, 不要传这个字段。
   */
  total?: number;
  defaultPageSize?: number;
  defaultSort?: { field: string; order: "ascend" | "descend" };
  /**
   * 列 key -> 后端查询参数。页面通常只写 `{ status: "status", appKey: "app_key" }`。
   * 未声明的列筛选不会进入 params(但仍留在 `query.filters` 里)。
   */
  filterParams?: ServerFilterParamMap;
  /** 排序参数名; 默认 DRF 风格的 "ordering"(降序前缀 "-")。 */
  sortParam?: string;
  /** 自定义排序序列化, 覆盖 sortParam 的默认拼法。 */
  serializeSort?: (sort: { field: string; order: "ascend" | "descend" }) => ServerTableParams;
}

export interface UseServerTableResult<T> {
  /** 原始状态; 需要自定义拼参数时用。 */
  query: ServerTableQuery;
  /** 已按 filterParams/sortParam 映射好的请求参数(含 page / page_size)。 */
  params: ServerTableParams;
  /** 展开到 AppTable 上: `<AppTable {...serverTable.tableProps} ... />` */
  tableProps: Pick<AppTableProps<T>, "pagination" | "onChange">;
  /** 当前生效的总条数(`options.total` 优先, 否则取最近一次 setTotal 的值)。 */
  total: number;
  setPage: (page: number, pageSize?: number) => void;
  /**
   * 回填后端返回的总条数, 之后 `tableProps.pagination.total` 就是它,
   * 页面不用再手工拼 `pagination={{ current, pageSize, total }}`。
   *
   * 可以直接在渲染期调用(`serverTable.setTotal(data?.pagination.total_items)`):
   * 内部对相同值做等值短路, 不会造成重渲染循环; 传 undefined / null 视为
   * 「这次还不知道」, 保留上一次的总数, 避免请求刷新时分页条闪一下 0。
   */
  setTotal: (total: number | null | undefined) => void;
  reset: () => void;
}

/**
 * 服务端分页/排序/筛选的唯一状态容器。
 *
 * 这里集中了三件本来会散落到每个页面的事:
 * 1. 分页状态与 APP_TABLE_PAGE_SIZE_OPTIONS 的默认页长;
 * 2. 排序或筛选变化时页码强制回到第 1 页(否则会翻到不存在的页);
 * 3. antd `onChange(pagination, filters, sorter)` -> 后端查询参数的映射。
 */
export function useServerTable<T>(options: UseServerTableOptions = {}): UseServerTableResult<T> {
  const {
    defaultPageSize = APP_TABLE_DEFAULT_PAGE_SIZE,
    defaultSort,
    filterParams,
    serializeSort,
    sortParam = "ordering",
    total,
  } = options;

  const initialQuery = useMemo<ServerTableQuery>(
    () => ({
      page: 1,
      pageSize: defaultPageSize,
      sortField: defaultSort?.field,
      sortOrder: defaultSort?.order,
      filters: {},
    }),
    [defaultPageSize, defaultSort?.field, defaultSort?.order],
  );

  const [query, setQuery] = useState<ServerTableQuery>(initialQuery);
  // 总条数只有请求回来后才知道, 因此和分页/排序/筛选状态分开存。
  const [lateTotal, setLateTotal] = useState<number | undefined>(undefined);

  const onChange = useCallback<NonNullable<TableProps<T>["onChange"]>>(
    (nextPagination, nextFilters, nextSorter, extra) => {
      const sorter = Array.isArray(nextSorter) ? nextSorter[0] : nextSorter;
      const order = normalizeSortOrder(sorter?.order);
      setQuery((previous) => ({
        // 排序/筛选变化后旧页码可能已越界, 统一回到第 1 页。
        page: extra.action === "paginate" ? (nextPagination.current ?? previous.page) : 1,
        pageSize: nextPagination.pageSize ?? previous.pageSize,
        sortField: order ? sorterField(sorter) : undefined,
        sortOrder: order,
        filters: normalizeFilters(nextFilters),
      }));
    },
    [],
  );

  const setPage = useCallback((page: number, pageSize?: number) => {
    setQuery((previous) => ({ ...previous, page, pageSize: pageSize ?? previous.pageSize }));
  }, []);

  const setTotal = useCallback(
    (next: number | null | undefined) => {
      // 等值短路必须在调用 setState 之前: 渲染期的 setState 不看新旧值是否相同,
      // 只要调用了就会再渲染一轮, 无条件调用会直接撞上 React 的 25 轮上限。
      if (next === null || next === undefined || next === lateTotal) {
        return;
      }
      setLateTotal(next);
    },
    [lateTotal],
  );

  const reset = useCallback(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  const params = useMemo<ServerTableParams>(() => {
    const next: ServerTableParams = {
      page: query.page,
      page_size: query.pageSize,
      ...filtersToParams(query.filters, filterParams),
    };
    if (query.sortField && query.sortOrder) {
      const sort = { field: query.sortField, order: query.sortOrder };
      Object.assign(next, serializeSort ? serializeSort(sort) : defaultSortParams(sortParam, sort));
    }
    return next;
  }, [filterParams, query.filters, query.page, query.pageSize, query.sortField, query.sortOrder, serializeSort, sortParam]);

  // options.total 优先(老用法), 否则用 setTotal 回填的值。
  const effectiveTotal = total ?? lateTotal ?? 0;

  const tableProps = useMemo<Pick<AppTableProps<T>, "pagination" | "onChange">>(
    () => ({
      pagination: { current: query.page, pageSize: query.pageSize, total: effectiveTotal },
      onChange,
    }),
    [onChange, query.page, query.pageSize, effectiveTotal],
  );

  return { query, params, tableProps, total: effectiveTotal, setPage, setTotal, reset };
}

/**
 * 把 antd 的筛选状态映射成后端查询参数。
 * 页面通常只需要声明 `{ status: "status", appKey: "app_key" }`;
 * 需要多值或自定义拼法时用 ServerFilterParam。
 */
export function filtersToParams(
  filters: Record<string, string[]>,
  map: ServerFilterParamMap | undefined,
): ServerTableParams {
  if (!map) {
    return {};
  }
  const params: ServerTableParams = {};
  for (const [columnKey, values] of Object.entries(filters)) {
    const config = map[columnKey];
    if (config === undefined || values.length === 0) {
      continue;
    }
    const normalized: ServerFilterParam = typeof config === "string" ? { param: config } : config;
    const value = normalized.serialize
      ? normalized.serialize(values)
      : normalized.multiple
        ? values
        : values[0];
    if (value !== undefined && value !== "") {
      params[normalized.param] = value;
    }
  }
  return params;
}

/**
 * `useServerTable().params` -> 查询串。
 *
 * 每张服务端分页表都要把同一份参数对象拼成 URL, 因此只在这里实现一次:
 * 空值不进串(与后端「不传即不过滤」的口径一致), 数组按同名多值展开,
 * 键顺序沿用参数对象的插入顺序(page / page_size 在前), 可直接当查询缓存键用。
 */
export function serverTableQuery(params: ServerTableParams, extra: Record<string, string> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries({ ...params, ...extra })) {
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== "") {
          search.append(key, item);
        }
      }
      continue;
    }
    const normalized = String(value);
    if (normalized !== "") {
      search.set(key, normalized);
    }
  }
  return search.toString();
}

/**
 * 把总条数补进一份现成的 `tableProps`。
 *
 * 常规写法是 `serverTable.setTotal(total)`(总数直接进 `tableProps`);
 * 只有「拿不到 hook 本体、手里只有 tableProps」时(例如某个自定义 hook 只把
 * tableProps 透出来)才需要这个纯函数版本。
 */
export function tablePropsWithTotal<T>(
  tableProps: Pick<AppTableProps<T>, "pagination" | "onChange">,
  total: number,
): Pick<AppTableProps<T>, "pagination" | "onChange"> {
  return {
    ...tableProps,
    pagination: tableProps.pagination === false ? false : { ...tableProps.pagination, total },
  };
}

function defaultSortParams(
  sortParam: string,
  sort: { field: string; order: "ascend" | "descend" },
): ServerTableParams {
  return { [sortParam]: sort.order === "descend" ? `-${sort.field}` : sort.field };
}

function normalizeSortOrder(order: SortOrder | undefined): "ascend" | "descend" | undefined {
  return order === "ascend" || order === "descend" ? order : undefined;
}

function sorterField<T>(sorter: SorterResult<T> | undefined): string | undefined {
  if (!sorter) {
    return undefined;
  }
  if (sorter.columnKey !== undefined) {
    return String(sorter.columnKey);
  }
  if (Array.isArray(sorter.field)) {
    return sorter.field.map(String).join(".");
  }
  return sorter.field === undefined ? undefined : String(sorter.field);
}

function normalizeFilters(filters: Record<string, FilterValue | null>): Record<string, string[]> {
  const normalized: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value && value.length > 0) {
      normalized[key] = value.map(String);
    }
  }
  return normalized;
}

/* ------------------------------------------------------------------ */
/* 列筛选助手                                                          */
/* ------------------------------------------------------------------ */

/** textFilter 的返回值; 直接展开到列定义上。 */
export type TextFilterColumn<T> = Required<Pick<ColumnType<T>, "filterDropdown" | "onFilter">>;

/** enumFilter 的返回值; 直接展开到列定义上。 */
export type EnumFilterColumn<T> = Required<Pick<ColumnType<T>, "filters" | "onFilter">>;

export interface TextFilterOptions<T> {
  /** 默认读 `record[columnKey]`; 嵌套字段或需要拼接多字段时自定义。 */
  getValue?: (record: T) => string | null | undefined;
  /** 覆盖输入框占位符; 默认走 i18n。 */
  placeholder?: string;
}

/**
 * 文本子串筛选(antd 没有内建)。大小写不敏感, 空关键字视为不筛选。
 * 用法: `{ title: "名称", dataIndex: "name", key: "name", ...textFilter<Row>("name") }`
 */
export function textFilter<T>(columnKey: string, options: TextFilterOptions<T> = {}): TextFilterColumn<T> {
  const { getValue, placeholder } = options;
  return {
    filterDropdown: (props: FilterDropdownProps) => <TextFilterDropdown {...props} placeholder={placeholder} />,
    onFilter: (value, record) => {
      const keyword = String(value).trim().toLowerCase();
      if (keyword === "") {
        return true;
      }
      const raw = getValue ? getValue(record) : readField(record, columnKey);
      return String(raw ?? "").toLowerCase().includes(keyword);
    },
  };
}

export interface EnumFilterOption {
  label: ReactNode;
  value: string;
}

export interface EnumFilterOptions<T> {
  /** 默认读 `record[columnKey]`; 返回数组时按「包含」匹配。 */
  getValue?: (record: T) => string | string[] | null | undefined;
}

/**
 * 枚举筛选: 生成 antd 内建的 `filters` 复选下拉 + 精确匹配 `onFilter`。
 * 用法: `{ ...enumFilter<Row>("status", [{ label: t("..."), value: "active" }]) }`
 */
export function enumFilter<T>(
  columnKey: string,
  options: readonly EnumFilterOption[],
  config: EnumFilterOptions<T> = {},
): EnumFilterColumn<T> {
  const { getValue } = config;
  return {
    filters: options.map((option) => ({ text: option.label, value: option.value })),
    onFilter: (value, record) => {
      const raw = getValue ? getValue(record) : readField(record, columnKey);
      if (Array.isArray(raw)) {
        return raw.map(String).includes(String(value));
      }
      return raw !== null && raw !== undefined && String(raw) === String(value);
    },
  };
}

export function readField<T>(record: T, columnKey: string): unknown {
  return (record as Record<string, unknown>)[columnKey];
}

function TextFilterDropdown({
  clearFilters,
  confirm,
  placeholder,
  selectedKeys,
  setSelectedKeys,
}: FilterDropdownProps & { placeholder?: string }) {
  const { t } = useI18n();
  const value = selectedKeys.length === 0 ? "" : String(selectedKeys[0]);

  return (
    // 下拉内部的键盘事件不能冒泡到表头, 否则空格/回车会触发排序。
    <div className="flex w-56 flex-col gap-2 p-2" onKeyDown={(event) => event.stopPropagation()}>
      <Input
        aria-label={t("table.filter.inputLabel")}
        autoFocus
        onChange={(event) => setSelectedKeys(toSelectedKeys(event.target.value))}
        onPressEnter={() => confirm()}
        placeholder={placeholder ?? t("table.filter.placeholder")}
        size="small"
        value={value}
      />
      <div className="flex items-center justify-end gap-2">
        <AntdButton
          onClick={() => {
            setSelectedKeys([]);
            clearFilters?.({ confirm: true, closeDropdown: true });
          }}
          size="small"
          type="text"
        >
          {t("table.filter.reset")}
        </AntdButton>
        <AntdButton onClick={() => confirm()} size="small" type="primary">
          {t("table.filter.confirm")}
        </AntdButton>
      </div>
    </div>
  );
}

function toSelectedKeys(value: string): Key[] {
  return value === "" ? [] : [value];
}

/* ------------------------------------------------------------------ */
/* 时间范围筛选                                                        */
/* ------------------------------------------------------------------ */

/** 起止时间; 空字符串表示这一端不限。值格式跟随 `inputType`(默认 datetime-local)。 */
export interface DateRangeValue {
  from: string;
  to: string;
}

/** 起止两端编码进同一个筛选值时的分隔符。 */
const DATE_RANGE_SEPARATOR = "~";

/** `{ from, to }` -> antd 的筛选值(空区间为 `[]`, 即「未筛选」)。 */
export function encodeDateRange({ from, to }: DateRangeValue): string[] {
  return from === "" && to === "" ? [] : [`${from}${DATE_RANGE_SEPARATOR}${to}`];
}

/** antd 的筛选值 -> `{ from, to }`; 无值时两端都是空字符串。 */
export function decodeDateRange(values: readonly unknown[] | null | undefined): DateRangeValue {
  const [from = "", to = ""] = String(values?.[0] ?? "").split(DATE_RANGE_SEPARATOR);
  return { from, to };
}

export interface DateRangeFilterOptions {
  /** 输入框类型; 默认 datetime-local, 只要日期时传 "date"。 */
  inputType?: "datetime-local" | "date";
  /** 覆盖两个输入框的 aria-label; 默认 `<paramKey>_from` / `<paramKey>_to`。 */
  fromLabel?: string;
  toLabel?: string;
}

/** dateRangeFilter 的返回值; 直接展开到列定义上(多出来的方法 antd 会忽略)。 */
export interface DateRangeFilterColumn<T> extends Required<Pick<ColumnType<T>, "filterDropdown">> {
  /** 筛选值 -> `{ from, to }`。 */
  decode: (values: readonly unknown[] | null | undefined) => DateRangeValue;
  /** `{ from, to }` -> 筛选值; 回填受控 `filteredValue` 时用。 */
  encode: (range: DateRangeValue) => string[];
  /** 起止 -> 后端参数 `<paramKey>_from` / `<paramKey>_to`; 空的一端不进参数。 */
  toParams: (from: string, to: string) => Record<string, string>;
}

/**
 * 时间范围筛选。antd 只内建「文本 / 枚举」两种筛选, 时间范围要自定义下拉,
 * 这里沿用 textFilter 下拉的结构(输入区 + 重置/确定), 只把输入换成两个时间框。
 *
 * `paramKey` 决定后端参数名与输入框 aria-label(默认 "created" -> created_from /
 * created_to)。起止两端编码进同一个筛选值, 因此一列只占 antd 的一个筛选槽。
 *
 * ```tsx
 * const submittedRange = dateRangeFilter<Row>("submitted");
 * const column = serverColumn(
 *   { ...dateTimeColumn<Row>({ key: "submitted_at", title: t("...") }), ...submittedRange },
 *   submittedRange.encode({ from, to }),
 * );
 * // 请求参数: submittedRange.toParams(from, to) -> { submitted_from, submitted_to }
 * ```
 */
export function dateRangeFilter<T>(
  paramKey = "created",
  options: DateRangeFilterOptions = {},
): DateRangeFilterColumn<T> {
  const { fromLabel = `${paramKey}_from`, inputType = "datetime-local", toLabel = `${paramKey}_to` } = options;
  return {
    filterDropdown: (props: FilterDropdownProps) => (
      <DateRangeFilterDropdown {...props} fromLabel={fromLabel} inputType={inputType} toLabel={toLabel} />
    ),
    decode: decodeDateRange,
    encode: encodeDateRange,
    toParams: (from, to) => {
      const params: Record<string, string> = {};
      if (from !== "") {
        params[`${paramKey}_from`] = from;
      }
      if (to !== "") {
        params[`${paramKey}_to`] = to;
      }
      return params;
    },
  };
}

function DateRangeFilterDropdown({
  clearFilters,
  confirm,
  fromLabel,
  inputType,
  selectedKeys,
  setSelectedKeys,
  toLabel,
}: FilterDropdownProps & { fromLabel: string; inputType: string; toLabel: string }) {
  const { t } = useI18n();
  const { from, to } = decodeDateRange(selectedKeys);

  return (
    // 下拉内部的键盘事件不能冒泡到表头, 否则空格/回车会触发排序。
    <div className="flex w-64 flex-col gap-2 p-2" onKeyDown={(event) => event.stopPropagation()}>
      <Input
        aria-label={fromLabel}
        onChange={(event) => setSelectedKeys(encodeDateRange({ from: event.target.value, to }))}
        size="small"
        type={inputType}
        value={from}
      />
      <Input
        aria-label={toLabel}
        onChange={(event) => setSelectedKeys(encodeDateRange({ from, to: event.target.value }))}
        size="small"
        type={inputType}
        value={to}
      />
      <div className="flex items-center justify-end gap-2">
        <AntdButton
          onClick={() => {
            setSelectedKeys([]);
            clearFilters?.({ confirm: true, closeDropdown: true });
          }}
          size="small"
          type="text"
        >
          {t("table.filter.reset")}
        </AntdButton>
        <AntdButton onClick={() => confirm()} size="small" type="primary">
          {t("table.filter.confirm")}
        </AntdButton>
      </div>
    </div>
  );
}
