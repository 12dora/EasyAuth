import type { TableProps } from "antd";
import type { FilterValue } from "antd/es/table/interface";
import { useCallback, useMemo, useState } from "react";

import type { AppTableProps } from "./AppTable";
import { defaultSortParams, ORDERING_PARAM, sortValueFromSorter } from "./ordering";

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

function normalizeFilters(filters: Record<string, FilterValue | null>): Record<string, string[]> {
  const normalized: Record<string, string[]> = {};
  for (const [key, value] of Object.entries(filters)) {
    if (value && value.length > 0) {
      normalized[key] = value.map(String);
    }
  }
  return normalized;
}
