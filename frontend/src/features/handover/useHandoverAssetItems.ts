/** 交接资产条目的搜索、防抖、分页查询与查询错误状态。 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { HandoverAssetItemsPage, HandoverAssetType } from "../../lib/domain";
import { assetItemsQueryKey, type ActionSnapshotScope } from "./actionSnapshotCache";
import { handleSnapshotStaleError } from "./handoverOverrideErrors";
import { handoverAssetTypePath } from "./surface";

const PAGE_SIZE = 50;

interface HandoverAssetItemsOptions {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  snapshotEpoch: number;
  loadedOverrides: boolean;
  setError: (error: string | null) => void;
  resetLocalOverrideState: () => void;
  onSnapshotStale?: () => void;
}

export function useHandoverAssetItems({
  scope,
  assetType,
  snapshotEpoch,
  loadedOverrides,
  setError,
  resetLocalOverrideState,
  onSnapshotStale,
}: HandoverAssetItemsOptions) {
  const { t } = useI18n();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const basePath = handoverAssetTypePath(scope.surface, scope.taskId, scope.appKey, assetType.type);
  const itemsQuery = useQuery({
    queryKey: assetItemsQueryKey(scope, assetType.type, snapshotEpoch, page, debouncedSearch),
    queryFn: () =>
      apiRequest<HandoverAssetItemsPage>(
        `${basePath}/items?page=${page}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(debouncedSearch)}`,
      ),
    enabled: loadedOverrides,
  });

  useEffect(() => {
    if (!itemsQuery.error) {
      return;
    }
    const result = handleSnapshotStaleError(itemsQuery.error, {
      message: t("handover.portal.detail.snapshotStale"),
      setError,
      resetLocalOverrideState,
      onSnapshotStale,
    });
    if (result.handled) {
      return;
    }
    if (result.reason === "downstream_locked") {
      setError(t("handover.portal.detail.downstreamLocked"));
      return;
    }
    setError((itemsQuery.error as Error).message);
  }, [itemsQuery.error, onSnapshotStale, resetLocalOverrideState, setError, t]);

  const totalPages = Math.max(1, Math.ceil((itemsQuery.data?.total ?? 0) / PAGE_SIZE));
  return {
    search,
    onSearchChange: (value: string) => {
      setSearch(value);
      setPage(1);
    },
    page,
    setPage,
    totalPages,
    total: itemsQuery.data?.total ?? 0,
    items: itemsQuery.data?.items ?? [],
    showStaleBanner: Boolean(itemsQuery.data?.stale) && !debouncedSearch,
    isFetching: itemsQuery.isFetching,
    itemsLoading: loadedOverrides && itemsQuery.isLoading && !itemsQuery.isError,
    itemsFailed: itemsQuery.isError,
    isError: itemsQuery.isError,
  };
}
