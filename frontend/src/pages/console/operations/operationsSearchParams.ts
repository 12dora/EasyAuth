import { useSearchParams } from "react-router-dom";

import {
  searchParamsWithOrdering,
  type OrderingFieldMap,
  type ServerSortValue,
} from "../../../components/antd/AppTable";
import { paginationFromSearchParams, type OperationsPagination } from "./operationQuery";
import { searchParamsWithFilters, type OperationFilterMap } from "./operationFilterMap";

export interface OperationsSearchParams {
  searchParams: URLSearchParams;
  pagination: OperationsPagination;
  updateSearchParam: (key: string, value: string) => void;
  updatePagination: (pagination: OperationsPagination) => void;
  /** 表头筛选变化: 写回 URL 并回到第 1 页。 */
  updateFilters: (filters: Record<string, string[]>, map: OperationFilterMap) => void;
  /** 表头排序变化: 写回 URL 的 ordering 并回到第 1 页。 */
  updateSort: (sort: ServerSortValue | undefined, map: OrderingFieldMap) => void;
}

export function useOperationsSearchParams(): OperationsSearchParams {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = paginationFromSearchParams(searchParams);

  const updateSearchParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value === "") {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    next.set("page", "1");
    setSearchParams(next);
  };
  const updatePagination = (nextPagination: OperationsPagination) => {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPagination.page));
    next.set("page_size", String(nextPagination.pageSize));
    setSearchParams(next);
  };
  const updateFilters = (filters: Record<string, string[]>, map: OperationFilterMap) => {
    setSearchParams(searchParamsWithFilters(searchParams, filters, map));
  };
  const updateSort = (sort: ServerSortValue | undefined, map: OrderingFieldMap) => {
    setSearchParams(searchParamsWithOrdering(searchParams, sort, map));
  };

  return { searchParams, pagination, updateSearchParam, updatePagination, updateFilters, updateSort };
}
