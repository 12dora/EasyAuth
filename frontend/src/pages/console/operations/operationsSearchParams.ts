import { useCallback } from "react";
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
  /** 一次写回多个查询参数(日期范围起止必须同时落盘, 不能各写各的)。 */
  updateSearchParams: (updates: Record<string, string>) => void;
  updatePagination: (pagination: OperationsPagination) => void;
  /** 表头筛选变化: 写回 URL 并回到第 1 页。 */
  updateFilters: (filters: Record<string, string[]>, map: OperationFilterMap) => void;
  /** 表头排序变化: 写回 URL 的 ordering 并回到第 1 页。 */
  updateSort: (sort: ServerSortValue | undefined, map: OrderingFieldMap) => void;
}

export function useOperationsSearchParams(): OperationsSearchParams {
  const [searchParams, setSearchParams] = useSearchParams();
  const pagination = paginationFromSearchParams(searchParams);

  const updateSearchParams = useCallback((updates: Record<string, string>) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      for (const [key, value] of Object.entries(updates)) {
        if (value === "") {
          next.delete(key);
        } else {
          next.set(key, value);
        }
      }
      next.set("page", "1");
      return next;
    });
  }, [setSearchParams]);
  const updateSearchParam = useCallback(
    (key: string, value: string) => updateSearchParams({ [key]: value }),
    [updateSearchParams],
  );
  const updatePagination = useCallback((nextPagination: OperationsPagination) => {
    setSearchParams((previous) => {
      const next = new URLSearchParams(previous);
      next.set("page", String(nextPagination.page));
      next.set("page_size", String(nextPagination.pageSize));
      return next;
    });
  }, [setSearchParams]);
  const updateFilters = useCallback((filters: Record<string, string[]>, map: OperationFilterMap) => {
    setSearchParams((previous) => searchParamsWithFilters(previous, filters, map));
  }, [setSearchParams]);
  const updateSort = useCallback((sort: ServerSortValue | undefined, map: OrderingFieldMap) => {
    setSearchParams((previous) => searchParamsWithOrdering(previous, sort, map));
  }, [setSearchParams]);

  return {
    searchParams,
    pagination,
    updateSearchParam,
    updateSearchParams,
    updatePagination,
    updateFilters,
    updateSort,
  };
}
