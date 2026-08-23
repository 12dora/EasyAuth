import type { PaginationState } from "@tanstack/react-table";
import { useSearchParams } from "react-router-dom";

import { paginationFromSearchParams } from "./operationQuery";

export interface OperationsSearchParams {
  searchParams: URLSearchParams;
  pagination: PaginationState;
  updateSearchParam: (key: string, value: string) => void;
  updatePagination: (
    updater: PaginationState | ((current: PaginationState) => PaginationState),
  ) => void;
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
  const updatePagination = (
    updater: PaginationState | ((current: PaginationState) => PaginationState),
  ) => {
    const nextPagination = typeof updater === "function" ? updater(pagination) : updater;
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPagination.pageIndex + 1));
    next.set("page_size", String(nextPagination.pageSize));
    setSearchParams(next);
  };

  return { searchParams, pagination, updateSearchParam, updatePagination };
}
