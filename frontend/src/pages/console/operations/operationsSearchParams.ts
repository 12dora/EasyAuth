import { useSearchParams } from "react-router-dom";

import { paginationFromSearchParams, type OperationsPagination } from "./operationQuery";
import { searchParamsWithFilters, type OperationFilterMap } from "./operationFilterMap";

export interface OperationsSearchParams {
  searchParams: URLSearchParams;
  pagination: OperationsPagination;
  updateSearchParam: (key: string, value: string) => void;
  updatePagination: (pagination: OperationsPagination) => void;
  /** 表头筛选变化: 写回 URL 并回到第 1 页。 */
  updateFilters: (filters: Record<string, string[]>, map: OperationFilterMap) => void;
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

  return { searchParams, pagination, updateSearchParam, updatePagination, updateFilters };
}
