/** 资产条目 override 的视图接口组合, 对外保持单一 hook 契约。 */

import { useState } from "react";

import type { HandoverAssetItem, HandoverAssetType } from "../../lib/domain";
import type { ActionSnapshotScope } from "./actionSnapshotCache";
import {
  applyItemDraft,
  effectiveOverride,
  matchesTypeDefault,
  mergeItemDraft,
  type DraftOverride,
} from "./assetAllocatorModel";
import { useHandoverAssetItems } from "./useHandoverAssetItems";
import { useHandoverOverrides } from "./useHandoverOverrides";

export interface AssetTypeOverridesOptions {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  readOnly: boolean;
  snapshotEpoch: number;
  onSaved: (result: { override_count: number; confirm_version: number; overrides_version: number }) => void;
  onBusyChange?: (busy: boolean) => void;
  onSnapshotStale?: () => void;
}

export function useAssetTypeOverrides(options: AssetTypeOverridesOptions) {
  const { scope, assetType, readOnly, snapshotEpoch, onSnapshotStale } = options;
  const [error, setError] = useState<string | null>(null);
  const overrides = useHandoverOverrides({ ...options, setError });
  const assetItems = useHandoverAssetItems({
    scope,
    assetType,
    snapshotEpoch,
    loadedOverrides: overrides.loadedOverrides,
    setError,
    resetLocalOverrideState: overrides.resetLocalOverrideState,
    onSnapshotStale,
  });

  const effectiveForItem = (item: HandoverAssetItem): DraftOverride =>
    effectiveOverride(overrides.drafts, item, assetType);
  const isOverridden = (item: HandoverAssetItem): boolean =>
    !matchesTypeDefault(effectiveForItem(item), assetType);
  const updateItem = (item: HandoverAssetItem, next: Partial<DraftOverride>) => {
    const merged = mergeItemDraft(overrides.drafts, item, assetType, next);
    overrides.setDrafts((current) => applyItemDraft(current, merged, assetType));
    setError(null);
  };
  const queriesSettled =
    overrides.loadedOverrides &&
    !overrides.isFetching &&
    !assetItems.isFetching &&
    !overrides.isError &&
    !assetItems.isError;

  return {
    search: assetItems.search,
    onSearchChange: assetItems.onSearchChange,
    page: assetItems.page,
    setPage: assetItems.setPage,
    totalPages: assetItems.totalPages,
    total: assetItems.total,
    items: assetItems.items,
    showStaleBanner: assetItems.showStaleBanner,
    error,
    incompleteTransferDraft: overrides.incompleteTransferDraft,
    effectiveForItem,
    isOverridden,
    updateItem,
    editorsLocked: readOnly || overrides.saving,
    saving: overrides.saving,
    canSubmit: queriesSettled && !readOnly && !overrides.saving && !overrides.incompleteTransferDraft,
    overridesLoading: overrides.overridesLoading,
    overridesFailedBeforeLoad: overrides.overridesFailedBeforeLoad,
    itemsLoading: assetItems.itemsLoading,
    itemsFailed: assetItems.itemsFailed && Boolean(error),
    requestSave: overrides.requestSave,
  };
}
