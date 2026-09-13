import { Button as AntdButton, DatePicker, Input, Table } from "antd";
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
import dayjs, { type Dayjs } from "dayjs";
import { useCallback, useMemo, useState, type Key, type ReactNode } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { cn } from "../../lib/cn";
import type { Translator } from "../../lib/status";
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

/**
 * 分页条的「单行」约定 class; 样式在 `src/styles/features/app-table.css`。
 *
 * antd 的 `.ant-pagination` 是 `flex-wrap: wrap`, 容器一窄「共 x 条 / 页码 / 每页条数」
 * 就会折成两三行, 把表格下沿顶下去。这个 class 把它钉成 `flex-wrap: nowrap`,
 * 并让分页条自己横向滚动(而不是换行), 因此常量与选择器必须成对存在 ——
 * `AppTable.test.tsx` 同时锁住「元素带这个 class」和「样式表里有对应规则」。
 */
export const APP_TABLE_PAGINATION_CLASS = "app-table-pagination";

export interface AppTableProps<T> extends Omit<TableProps<T>, "rowKey" | "pagination" | "locale" | "caption"> {
  /** 必填: 行身份只能来自数据字段, 不允许回落数组下标。 */
  rowKey: NonNullable<TableProps<T>["rowKey"]>;
  /**
   * 表格的无障碍名字, 渲染成视觉隐藏的原生 `<caption>`。
   *
   * 一个页面上有多张表(门户的授权/申请/审批)时, 屏幕阅读器只会念 "table",
   * 用户无从分辨; `<caption>` 是 HTML 给表格命名的原生方式, 直接成为
   * `role="table"` 的可及名称, 不需要额外的 aria 属性。
   * 隐藏样式在 `src/styles/features/app-table.css` 的 `.ant-table-caption`
   * (用 clip 而不是 display:none, 否则名字会一起从无障碍树里消失)。
   */
  ariaLabel?: string;
  /**
   * 表格的最小宽度, 写进 `scroll.x`。列宽之和已经确定时传像素数。
   *
   * 有行数据时不传也**始终**有 `scroll.x`(回落 "max-content"): 横向滚动必须落在 antd
   * 自己的 `.ant-table-content` 上, 否则超宽表格会把整页撑出横向滚动条; 而且 fixed 布局下
   * 没有剩余宽度时无宽度列会被压到 0px, "max-content" 让它们退回内容宽度。
   * 表格样式里的 `min-width: 100%` 由 antd 写死, 宽屏下仍然铺满容器。
   *
   * 空表例外, 见 `mergedScroll` 的注释。
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
  ariaLabel,
  className,
  dataSource,
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
      // 页面即使自己传了 className 也不能丢掉「单行分页」约定, 因此合并在展开之后。
      className: cn(APP_TABLE_PAGINATION_CLASS, pagination?.className),
    };
  }, [pagination, t]);

  const isEmpty = (dataSource?.length ?? 0) === 0;

  /*
   * scroll.x 一定要有值: 它是 antd 给 `.ant-table-content` 挂 overflow-x:auto 的开关,
   * 少了它超宽表格会把整页撑出横向滚动条。有行数据时宽度取页面显式传的 scroll.x,
   * 其次 minWidth, 都没有就用 "max-content"(列按内容取宽, 表格自身仍带 min-width:100%)。
   *
   * 空表是唯一例外: minWidth 要让位给 `true`(= 只要滚动容器, 表格宽度交给布局),
   * 否则空态框会和表头错位。开了横向滚动后 rc-table 把空态包进
   * `.ant-table-expanded-row-fixed`, 给它写死 `width: <容器宽度>px; position: sticky; left: 0`
   * —— 空态框钉在可视区、宽度是容器宽, 而表头那张 `<table>` 被 minWidth 撑到更宽
   * (人员管理: 容器 860 / 表头 960)。于是没有一行数据的表格也带一条横向滚动条,
   * 一滚表头整排移动、空态框纹丝不动, 末尾的「操作」列还被 sticky 钉在右侧盖住相邻列。
   * 而空表本来就没有行内容需要 minWidth 去保住列宽 —— 表头只是个图例。
   * 换成 `x: true` 后表格按 `table-layout: fixed` 正好铺满容器, 表头与空态框同宽同起点;
   * 容器窄到连各列声明的宽度都放不下时表格仍会溢出, 那时滚动容器还在,
   * 「页面永不横向滚动」的约定不受影响。
   */
  const mergedScroll = useMemo<TableProps<T>["scroll"]>(() => {
    if (isEmpty) {
      return { ...scroll, x: true };
    }
    return { ...scroll, x: scroll?.x ?? minWidth ?? "max-content" };
  }, [isEmpty, minWidth, scroll]);

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
      caption={ariaLabel}
      className={cn("w-full", className)}
      dataSource={dataSource}
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

/** 后端排序参数名; DRF 风格, 降序前缀 "-"。 */
export const ORDERING_PARAM = "ordering";

/** 单字段排序; `field` 是列 key, 由 serializeSort 映射成后端公开字段名。 */
export interface ServerSortValue {
  field: string;
  order: "ascend" | "descend";
}

/**
 * 当前排序状态。列要显示排序指示器时把它交给 `serverSortColumn`,
 * 表头图标就与实际请求参数同源(而不是 antd 自己的内部状态)。
 */
export interface ServerSortState {
  /** 当前排序列的 `key`(未设 key 时为 dataIndex); 无排序为 undefined。 */
  sortField?: string;
  sortOrder?: "ascend" | "descend";
}

export interface ServerTableQuery extends ServerSortState {
  /** 1 基页码。 */
  page: number;
  pageSize: number;
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
  /**
   * 首屏排序。产品口径是「表格一律不设默认排序」(首屏表头不带排序指示器,
   * 顺序交给后端的默认序), 所以页面不要传这个字段; 它只作为 hook 的能力保留。
   */
  defaultSort?: ServerSortValue;
  /**
   * 列 key -> 后端查询参数。页面通常只写 `{ status: "status", appKey: "app_key" }`。
   * 未声明的列筛选不会进入 params(但仍留在 `query.filters` 里)。
   */
  filterParams?: ServerFilterParamMap;
  /** 排序参数名; 默认 DRF 风格的 "ordering"(降序前缀 "-")。 */
  sortParam?: string;
  /**
   * 自定义排序序列化, 覆盖 sortParam 的默认拼法。
   * 列 key 与后端公开字段名不一致时用 `orderingSerializer(map)`, 不要各写各的拼法。
   */
  serializeSort?: (sort: ServerSortValue) => ServerTableParams;
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
   * 直接改排序(并回到第 1 页); 传 undefined 表示清空排序, 顺序交回后端默认序。
   * 表头点击不走这里, 它是给「排序随外部状态切换」的场景用的:
   * 例如门户审批切换待办/已处理页签时把表头排序清掉。
   */
  setSort: (sort: ServerSortValue | undefined) => void;
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
    sortParam = ORDERING_PARAM,
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
      const sort = sortValueFromSorter(nextSorter);
      setQuery((previous) => ({
        // 排序/筛选变化后旧页码可能已越界, 统一回到第 1 页。
        page: extra.action === "paginate" ? (nextPagination.current ?? previous.page) : 1,
        pageSize: nextPagination.pageSize ?? previous.pageSize,
        sortField: sort?.field,
        sortOrder: sort?.order,
        filters: normalizeFilters(nextFilters),
      }));
    },
    [],
  );

  const setPage = useCallback((page: number, pageSize?: number) => {
    setQuery((previous) => ({ ...previous, page, pageSize: pageSize ?? previous.pageSize }));
  }, []);

  const setSort = useCallback((sort: ServerSortValue | undefined) => {
    // 换了排序键的旧页码可能已越界, 与表头排序一样回到第 1 页。
    setQuery((previous) => ({ ...previous, page: 1, sortField: sort?.field, sortOrder: sort?.order }));
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

  return { query, params, tableProps, total: effectiveTotal, setPage, setSort, setTotal, reset };
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

function defaultSortParams(sortParam: string, sort: ServerSortValue): ServerTableParams {
  return { [sortParam]: sort.order === "descend" ? `-${sort.field}` : sort.field };
}

/** 列 key -> 后端公开排序字段名。映射表里没有的列不产生排序参数。 */
export type OrderingFieldMap = Readonly<Record<string, string>>;

/**
 * `useServerTable({ serializeSort })` 的唯一实现。
 *
 * 列 key 和后端公开字段名并不总是同一个词(门户申请的 `submitted_at` 列对应后端的
 * `created_at`、审批实例的 `template_key` 列对应 `template`、应用/团队的 `status`
 * 列对应库里的 `is_active`), 所以每张表要给一份小映射; 「asc/desc -> 有无 `-` 前缀」
 * 的拼法则只写这一份, 页面不要各写各的。
 *
 * ```ts
 * const serverTable = useServerTable<Row>({
 *   sortParam: "ordering",
 *   serializeSort: orderingSerializer({ created_at: "created_at", app: "app_key" }),
 * });
 * ```
 */
export function orderingSerializer(
  map: OrderingFieldMap,
  sortParam: string = ORDERING_PARAM,
): (sort: ServerSortValue) => ServerTableParams {
  return ({ field, order }) => {
    const backendField = map[field];
    return backendField === undefined ? {} : defaultSortParams(sortParam, { field: backendField, order });
  };
}

/**
 * 把 antd `onChange` 的 sorter 收成单字段排序。三态循环里取消排序时返回 undefined。
 * `useServerTable` 与运营分区的 URL 排序共用这一份, 不要各自再拆一次。
 */
export function sortValueFromSorter<T>(
  sorter: SorterResult<T> | SorterResult<T>[] | undefined,
): ServerSortValue | undefined {
  const first = Array.isArray(sorter) ? sorter[0] : sorter;
  const order = normalizeSortOrder(first?.order);
  if (!order) {
    return undefined;
  }
  const field = sorterField(first);
  return field === undefined ? undefined : { field, order };
}

/**
 * URL / 查询串上的 `ordering=field` / `ordering=-field` -> 列 key + 升降序。
 * 映射表按「列 key -> 后端字段」写, 这里反向查找; 对不上的值视为无排序。
 */
export function parseOrderingParam(
  value: string | null | undefined,
  map: OrderingFieldMap,
): ServerSortValue | undefined {
  if (value === null || value === undefined || value === "") {
    return undefined;
  }
  const descend = value.startsWith("-");
  const backendField = descend ? value.slice(1) : value;
  if (backendField === "") {
    return undefined;
  }
  const field = Object.keys(map).find((columnKey) => map[columnKey] === backendField);
  if (field === undefined) {
    return undefined;
  }
  return { field, order: descend ? "descend" : "ascend" };
}

/** `ordering` 查询值 -> 交给 `serverSortColumn` 的受控指示器状态。 */
export function sortStateFromOrdering(
  value: string | null | undefined,
  map: OrderingFieldMap,
): ServerSortState {
  const sort = parseOrderingParam(value, map);
  return { sortField: sort?.field, sortOrder: sort?.order };
}

/**
 * 把当前排序写进 URLSearchParams(运营分区用)。
 * 序列化走 `orderingSerializer`, 换列或取消时页码回到第 1 页。
 */
export function searchParamsWithOrdering(
  current: URLSearchParams,
  sort: ServerSortValue | undefined,
  map: OrderingFieldMap,
  sortParam: string = ORDERING_PARAM,
): URLSearchParams {
  const next = new URLSearchParams(current);
  const serialized = sort ? orderingSerializer(map, sortParam)(sort) : {};
  const ordering = serialized[sortParam];
  if (typeof ordering === "string" && ordering !== "") {
    next.set(sortParam, ordering);
  } else {
    next.delete(sortParam);
  }
  next.set("page", "1");
  return next;
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

/**
 * 起止时间; 空字符串表示这一端不限。
 * 写入 URL / 后端的是浏览器本地时区的日界, 带偏移的 ISO 8601
 * (`YYYY-MM-DDTHH:mm:ssZ`, 如 `2026-09-13T00:00:00+08:00`)。
 */
export interface DateRangeValue {
  from: string;
  to: string;
}

/** 工具栏与表头筛选共用的 RangePicker 宽度。 */
export const DATE_RANGE_CONTROL_WIDTH_PX = 260;

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
  /** 覆盖两个输入框的占位; 默认走 i18n `table.dateRange.from` / `to`。 */
  fromLabel?: string;
  toLabel?: string;
}

export interface DateRangeControlProps {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  /** 套在选择器外层的无障碍名。 */
  ariaLabel?: string;
  fromPlaceholder?: string;
  toPlaceholder?: string;
  allowClear?: boolean;
  size?: "small" | "middle" | "large";
  getPopupContainer?: (node: HTMLElement) => HTMLElement;
}

/**
 * 全站唯一的日期范围控件: antd RangePicker, 预设近7天 / 近30天 / 本月。
 * 授权明细工具栏与表头 `dateRangeFilter` 都走这里, 不要再各写一份。
 *
 * 展示按日。写回 URL / 后端时在浏览器本地时区取当日 00:00:00 / 23:59:59,
 * 并以带偏移的 ISO 8601 序列化(`format("YYYY-MM-DDTHH:mm:ssZ")`)。
 * 回读取字符串里的日历日, 不把带 Z / 偏移的瞬间换算成浏览器当天,
 * 避免再确认时日期被挪一天。
 */
export function DateRangeControl({
  allowClear = true,
  ariaLabel,
  fromPlaceholder,
  getPopupContainer,
  onChange,
  size = "middle",
  toPlaceholder,
  value,
}: DateRangeControlProps) {
  const { t } = useI18n();
  const picker = (
    <DatePicker.RangePicker
      allowClear={allowClear}
      allowEmpty={[true, true]}
      format="YYYY-MM-DD"
      getPopupContainer={getPopupContainer}
      onChange={(dates) => onChange(fromPickerValue(dates))}
      placeholder={[fromPlaceholder ?? t("table.dateRange.from"), toPlaceholder ?? t("table.dateRange.to")]}
      presets={dateRangePresets(t)}
      size={size}
      style={{ width: DATE_RANGE_CONTROL_WIDTH_PX }}
      value={toPickerValue(value)}
    />
  );
  if (ariaLabel === undefined) {
    return picker;
  }
  return (
    <div aria-label={ariaLabel} role="group">
      {picker}
    </div>
  );
}

function dateRangePresets(t: Translator): { label: string; value: [Dayjs, Dayjs] }[] {
  const today = dayjs();
  return [
    { label: t("table.dateRange.preset.last7Days"), value: [today.subtract(6, "day"), today] },
    { label: t("table.dateRange.preset.last30Days"), value: [today.subtract(29, "day"), today] },
    { label: t("table.dateRange.preset.thisMonth"), value: [today.startOf("month"), today.endOf("month")] },
  ];
}

function toPickerValue(range: DateRangeValue): [Dayjs | null, Dayjs | null] | null {
  const from = parseDateRangeBound(range.from);
  const to = parseDateRangeBound(range.to);
  if (from === null && to === null) {
    return null;
  }
  return [from, to];
}

function fromPickerValue(dates: [Dayjs | null, Dayjs | null] | null): DateRangeValue {
  const [from, to] = dates ?? [null, null];
  return {
    from: from ? formatDateRangeBound(from, "from") : "",
    to: to ? formatDateRangeBound(to, "to") : "",
  };
}

/** ISO 日界字符串开头的日历日。 */
const DATE_BOUND_DATE = /^(\d{4}-\d{2}-\d{2})/;

/**
 * 从 URL / 筛选值解析日历日: 取 ISO 字符串的日期部分, 忽略时区换算。
 * `2026-09-13T23:59:59Z` 与 `2026-09-13T00:00:00+08:00` 都显示 9 月 13 日。
 */
export function parseDateRangeBound(raw: string): Dayjs | null {
  if (raw === "") {
    return null;
  }
  const datePart = DATE_BOUND_DATE.exec(raw)?.[1];
  const parsed = datePart === undefined ? dayjs(raw) : dayjs(`${datePart}T00:00:00`);
  return parsed.isValid() ? parsed : null;
}

/** 把日历日格式化为本地时区的日起/日止瞬时, 带偏移。 */
export function formatDateRangeBound(day: Dayjs, bound: "from" | "to"): string {
  const boundary = bound === "from" ? day.startOf("day") : day.endOf("day");
  return boundary.format("YYYY-MM-DDTHH:mm:ssZ");
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
 * 时间范围筛选。antd 只内建「文本 / 枚举」两种筛选, 时间范围要自定义下拉;
 * 输入区走全站共用的 `DateRangeControl`(RangePicker + 预设)。
 *
 * `paramKey` 决定后端参数名(默认 "created" -> created_from / created_to)。
 * 起止两端编码进同一个筛选值, 因此一列只占 antd 的一个筛选槽。
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
  const { fromLabel, toLabel } = options;
  return {
    filterDropdown: (props: FilterDropdownProps) => (
      <DateRangeFilterDropdown {...props} fromLabel={fromLabel} toLabel={toLabel} />
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
  selectedKeys,
  setSelectedKeys,
  toLabel,
}: FilterDropdownProps & { fromLabel?: string; toLabel?: string }) {
  const { t } = useI18n();

  return (
    // 下拉内部的键盘事件不能冒泡到表头, 否则空格/回车会触发排序。
    <div className="flex flex-col gap-2 p-2" onKeyDown={(event) => event.stopPropagation()}>
      <DateRangeControl
        fromPlaceholder={fromLabel}
        onChange={(range) => setSelectedKeys(encodeDateRange(range))}
        toPlaceholder={toLabel}
        value={decodeDateRange(selectedKeys)}
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
