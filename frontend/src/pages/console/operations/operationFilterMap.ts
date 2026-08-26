import { filtersToParams, type ServerFilterParamMap } from "../../../components/antd/AppTable";

/**
 * 运营列表的「表头筛选 ↔ URL 查询参数」映射。
 *
 * 运营页的筛选条件由 URL 承载(FF-21: 可深链、可分享), 因此不能用 useServerTable
 * 的内部状态; 但「列 key -> 后端参数」这层映射仍然复用共享的 filtersToParams,
 * 页面不自己拼参数名。
 */

/** created_from / created_to 挂在同一个时间列上, 用分隔符编码成一个筛选值。 */
const DATE_RANGE_SEPARATOR = "~";
const DATE_FROM_PARAM = "created_from";
const DATE_TO_PARAM = "created_to";

export interface OperationFilterMap {
  /** 列 key -> 后端查询参数。 */
  params: ServerFilterParamMap;
  /** 承载 created_from/created_to 的时间列 key; 该分区没有时间列时省略。 */
  dateColumnKey?: string;
}

export const SECTION_FILTER_MAPS: Record<string, OperationFilterMap> = {
  "access-requests": {
    params: { user_id: "user_id", app_key: "app_key", status: "status" },
    dateColumnKey: "submitted_at",
  },
  // 授权列表的后端载荷没有 created_at 字段, 没有时间列可以挂 created_from/created_to,
  // 因此该分区的时间范围留在表格上方(全站唯一的例外筛选控件)。
  "access-grants": {
    params: {
      user_id: "user_id",
      app_key: "app_key",
      status: "status",
      version: "version",
      is_current: "current",
    },
  },
  audit: {
    params: { actor: "actor_id", app: "app_key" },
    dateColumnKey: "created_at",
  },
};

export interface DateRangeValue {
  from: string;
  to: string;
}

export function encodeDateRange({ from, to }: DateRangeValue): string[] {
  return from === "" && to === "" ? [] : [`${from}${DATE_RANGE_SEPARATOR}${to}`];
}

export function decodeDateRange(values: readonly unknown[] | undefined): DateRangeValue {
  const [from = "", to = ""] = String(values?.[0] ?? "").split(DATE_RANGE_SEPARATOR);
  return { from, to };
}

/** URL -> antd 的受控筛选值(列 key -> 选中值)。 */
export function filterValuesFromSearchParams(
  searchParams: URLSearchParams,
  map: OperationFilterMap,
): Record<string, string[]> {
  const filters: Record<string, string[]> = {};
  for (const [columnKey, config] of Object.entries(map.params)) {
    const value = searchParams.get(paramName(config));
    if (value) {
      filters[columnKey] = [value];
    }
  }
  if (map.dateColumnKey !== undefined) {
    const range = {
      from: searchParams.get(DATE_FROM_PARAM) ?? "",
      to: searchParams.get(DATE_TO_PARAM) ?? "",
    };
    const encoded = encodeDateRange(range);
    if (encoded.length > 0) {
      filters[map.dateColumnKey] = encoded;
    }
  }
  return filters;
}

/** antd 的筛选状态 -> URL; 未选中的筛选参数会被删除, 页码回到第 1 页。 */
export function searchParamsWithFilters(
  current: URLSearchParams,
  filters: Record<string, string[]>,
  map: OperationFilterMap,
): URLSearchParams {
  const next = new URLSearchParams(current);
  for (const config of Object.values(map.params)) {
    next.delete(paramName(config));
  }
  for (const [param, value] of Object.entries(filtersToParams(filters, map.params))) {
    next.set(param, String(value));
  }
  if (map.dateColumnKey !== undefined) {
    const { from, to } = decodeDateRange(filters[map.dateColumnKey]);
    setOrDelete(next, DATE_FROM_PARAM, from);
    setOrDelete(next, DATE_TO_PARAM, to);
  }
  next.set("page", "1");
  return next;
}

function paramName(config: ServerFilterParamMap[string]): string {
  return typeof config === "string" ? config : config.param;
}

function setOrDelete(params: URLSearchParams, key: string, value: string): void {
  if (value === "") {
    params.delete(key);
    return;
  }
  params.set(key, value);
}
