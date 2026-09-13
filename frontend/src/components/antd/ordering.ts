import type { SorterResult, SortOrder } from "antd/es/table/interface";

import type { ServerSortState, ServerSortValue, ServerTableParams } from "./useServerTable";

/** 后端排序参数名; DRF 风格, 降序前缀 "-"。 */
export const ORDERING_PARAM = "ordering";

/** 列 key -> 后端公开排序字段名。映射表里没有的列不产生排序参数。 */
export type OrderingFieldMap = Readonly<Record<string, string>>;

export function defaultSortParams(sortParam: string, sort: ServerSortValue): ServerTableParams {
  return { [sortParam]: sort.order === "descend" ? `-${sort.field}` : sort.field };
}

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
