import type { AppTableProps, ServerTableParams, UseServerTableResult } from "../../components/antd/AppTable";

/**
 * `useServerTable().params` -> 查询串。
 *
 * 三张服务端分页表(应用/人员/交接单)都要把同一份参数对象拼成 URL,
 * 因此只在这里实现一次: 空值不进串(与后端"不传即不过滤"的口径一致),
 * 键顺序沿用参数对象的插入顺序(page/page_size 在前), 可直接当查询缓存键用。
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
 * 把后端返回的总条数补进 useServerTable 的 tableProps。
 *
 * `useServerTable({ total })` 要求在建 hook 时就知道总数, 但总数来自那次
 * 用 hook 参数发出的请求, 声明顺序上拿不到; 因此 hook 只管分页/筛选状态,
 * 总数在拿到响应后由这里补齐。
 */
export function serverTableProps<T>(
  tableProps: UseServerTableResult<T>["tableProps"],
  total: number,
): Pick<AppTableProps<T>, "pagination" | "onChange"> {
  return {
    ...tableProps,
    pagination: tableProps.pagination === false ? false : { ...tableProps.pagination, total },
  };
}
