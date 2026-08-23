import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import type {
  HandoverAssetItem,
  HandoverAssetItemsPage,
  HandoverAssetType,
  HandoverOverridesPayload,
} from "../../lib/domain";
import { assetItemsQueryKey, overridesQueryKey, type ActionSnapshotScope } from "./actionSnapshotCache";
import {
  buildOverridesBody,
  draftsFromOverrides,
  applyItemDraft,
  effectiveOverride,
  hasIncompleteTransferDraft,
  matchesTypeDefault,
  mergeItemDraft,
  type DraftOverride,
} from "./assetAllocatorModel";
import { handoverAssetTypePath } from "./surface";

const PAGE_SIZE = 50;

export interface AssetTypeOverridesOptions {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  readOnly: boolean;
  snapshotEpoch: number;
  onSaved: (result: { override_count: number; confirm_version: number; overrides_version: number }) => void;
  onBusyChange?: (busy: boolean) => void;
  onSnapshotStale?: () => void;
}

/** 资产条目级 override 草稿的全部状态与网络交互; 视图只做渲染。 */
export function useAssetTypeOverrides({
  scope,
  assetType,
  readOnly,
  snapshotEpoch,
  onSaved,
  onBusyChange,
  onSnapshotStale,
}: AssetTypeOverridesOptions) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  /** 完整 override 草稿集合（跨页/搜索）；删除即从本 map 移除，不得再从服务端快照复活 */
  const [drafts, setDrafts] = useState<Record<string, DraftOverride>>({});
  const [loadedOverrides, setLoadedOverrides] = useState(false);
  const [overridesVersion, setOverridesVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  const basePath = handoverAssetTypePath(scope.surface, scope.taskId, scope.appKey, assetType.type);

  const overridesQuery = useQuery({
    queryKey: overridesQueryKey(scope, assetType.type, snapshotEpoch),
    queryFn: async () => apiRequest<HandoverOverridesPayload>(`${basePath}/overrides`),
  });

  useEffect(() => {
    if (!overridesQuery.data) {
      return;
    }
    setOverridesVersion(overridesQuery.data.overrides_version);
    setLoadedOverrides(true);
    setDrafts(draftsFromOverrides(overridesQuery.data.overrides));
    setError(null);
  }, [overridesQuery.data]);

  const resetLocalOverrideState = () => {
    setDrafts({});
    setLoadedOverrides(false);
    setOverridesVersion(0);
  };

  useEffect(() => {
    if (!overridesQuery.error) {
      return;
    }
    // overrides GET 失败不得永久挂在 loading；表面化错误
    setLoadedOverrides(false);
    const reason = apiErrorReason(overridesQuery.error);
    if (reason === "snapshot_stale") {
      setError(t("handover.portal.detail.snapshotStale"));
      resetLocalOverrideState();
      onSnapshotStale?.();
      return;
    }
    setError((overridesQuery.error as Error).message);
  }, [overridesQuery.error, onSnapshotStale, t]);

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
    const reason = apiErrorReason(itemsQuery.error);
    if (reason === "snapshot_stale") {
      setError(t("handover.portal.detail.snapshotStale"));
      resetLocalOverrideState();
      onSnapshotStale?.();
      return;
    }
    if (reason === "downstream_locked") {
      setError(t("handover.portal.detail.downstreamLocked"));
      return;
    }
    setError((itemsQuery.error as Error).message);
  }, [itemsQuery.error, onSnapshotStale, t]);

  const items = itemsQuery.data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((itemsQuery.data?.total ?? 0) / PAGE_SIZE));

  const effectiveForItem = (item: HandoverAssetItem): DraftOverride => effectiveOverride(drafts, item, assetType);

  const isOverridden = (item: HandoverAssetItem): boolean =>
    !matchesTypeDefault(effectiveForItem(item), assetType);

  const updateItem = (item: HandoverAssetItem, next: Partial<DraftOverride>) => {
    const merged = mergeItemDraft(drafts, item, assetType, next);
    setDrafts((current) => applyItemDraft(current, merged, assetType));
    setError(null);
  };

  const draftList = Object.values(drafts);
  const incompleteTransferDraft = hasIncompleteTransferDraft(draftList);

  const saveMutation = useMutation({
    mutationFn: async () => {
      // drafts 即完整替换集合：跨页删除必须在 drafts 中已生效，禁止从旧快照回填
      if (hasIncompleteTransferDraft(draftList)) {
        throw new Error(t("handover.allocator.receiverRequired"));
      }
      return apiRequest<{
        overrides_version: number;
        confirm_version: number;
        override_count: number;
        dropped_invalid: number;
      }>(`${basePath}/overrides`, {
        method: "PUT",
        body: { overrides_version: overridesVersion, overrides: buildOverridesBody(draftList, assetType) },
      });
    },
    onSuccess: (payload) => {
      setError(null);
      setOverridesVersion(payload.overrides_version);
      onSaved({
        override_count: payload.override_count,
        confirm_version: payload.confirm_version,
        overrides_version: payload.overrides_version,
      });
      void queryClient.invalidateQueries({ queryKey: overridesQueryKey(scope, assetType.type, snapshotEpoch) });
    },
    onError: async (err: Error) => {
      const reason = apiErrorReason(err);
      if (reason === "overrides_version_stale") {
        setError(t("handover.allocator.overridesStale"));
        await overridesQuery.refetch();
        return;
      }
      if (reason === "snapshot_stale") {
        setError(t("handover.portal.detail.snapshotStale"));
        resetLocalOverrideState();
        onSnapshotStale?.();
        return;
      }
      setError(err.message);
    },
  });

  useEffect(() => {
    onBusyChange?.(saveMutation.isPending || incompleteTransferDraft);
  }, [onBusyChange, saveMutation.isPending, incompleteTransferDraft]);

  // 保存中或仍在拉取权威集合时禁止提交/编辑，避免 PUT 期间改动被成功回流擦除
  const editorsLocked = readOnly || saveMutation.isPending;
  const queriesSettled =
    loadedOverrides &&
    !overridesQuery.isFetching &&
    !itemsQuery.isFetching &&
    !overridesQuery.isError &&
    !itemsQuery.isError;

  const requestSave = () => {
    if (incompleteTransferDraft) {
      setError(t("handover.allocator.receiverRequired"));
      return;
    }
    saveMutation.mutate();
  };

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
    items,
    showStaleBanner: Boolean(itemsQuery.data?.stale) && !debouncedSearch,
    error,
    incompleteTransferDraft,
    effectiveForItem,
    isOverridden,
    updateItem,
    editorsLocked,
    saving: saveMutation.isPending,
    canSubmit: queriesSettled && !readOnly && !saveMutation.isPending && !incompleteTransferDraft,
    overridesLoading: overridesQuery.isLoading && !overridesQuery.isError,
    overridesFailedBeforeLoad: overridesQuery.isError && !loadedOverrides,
    itemsLoading: loadedOverrides && itemsQuery.isLoading && !itemsQuery.isError,
    itemsFailed: itemsQuery.isError && Boolean(error),
    requestSave,
  };
}
