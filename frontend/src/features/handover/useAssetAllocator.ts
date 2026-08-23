import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import type { HandoverAction, HandoverAssetAction, HandoverAssetType, HandoverUserRef } from "../../lib/domain";
import { removeActionSnapshotQueries, type ActionSnapshotScope } from "./actionSnapshotCache";
import {
  countArrangedAssetTypes,
  hasIncompleteTypeTransfer,
  replaceAssetType,
  withOverrideCount,
  withTypeDefault,
} from "./assetAllocatorModel";
import { handoverAssetTypePath } from "./surface";

export interface AssetAllocatorPatch {
  asset_types?: HandoverAssetType[];
  confirm_version?: number;
  overrides_version?: number;
}

export interface AssetAllocatorOptions {
  scope: ActionSnapshotScope;
  action: HandoverAction;
  onActionUpdated?: (patch: AssetAllocatorPatch) => void;
  onBusyChange?: (busy: boolean) => void;
  onSnapshotStale?: () => void;
}

/** 资产类型级默认动作的本地态与 PATCH 交互。 */
export function useAssetAllocator({
  scope,
  action,
  onActionUpdated,
  onBusyChange,
  onSnapshotStale,
}: AssetAllocatorOptions) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [expandedType, setExpandedType] = useState<string | null>(null);
  const [localTypes, setLocalTypes] = useState(action.asset_types);
  const [typeError, setTypeError] = useState<string | null>(null);
  const [savingType, setSavingType] = useState(false);
  const [detailsBusy, setDetailsBusy] = useState(false);
  /** 412 后递增，写入 queryKey 使旧快照缓存不可复用 */
  const [snapshotEpoch, setSnapshotEpoch] = useState(0);

  useEffect(() => {
    setLocalTypes(action.asset_types);
  }, [action.asset_types]);

  // transfer 无接收人是显式非法草稿：禁止执行直到 PATCH 落库合法值（02 §6.1）
  const incompleteTypeTransfer = hasIncompleteTypeTransfer(localTypes);

  useEffect(() => {
    onBusyChange?.(savingType || detailsBusy || incompleteTypeTransfer);
  }, [onBusyChange, savingType, detailsBusy, incompleteTypeTransfer]);

  const handleSnapshotStale = () => {
    setExpandedType(null);
    setSnapshotEpoch((epoch) => epoch + 1);
    removeActionSnapshotQueries(queryClient, scope);
    setTypeError(t("handover.portal.detail.snapshotStale"));
    onSnapshotStale?.();
  };

  const patchType = async (
    assetType: HandoverAssetType,
    nextAction: HandoverAssetAction,
    nextUser: HandoverUserRef | null,
  ) => {
    // transfer 必须先本地展示接收人选择器，选中接收人后才 PATCH（01 §5.4 receiver_required）
    // 非法草稿期间 onBusyChange=true，父级禁用执行，避免用服务端旧 assignment 执行。
    if (nextAction === "transfer" && !nextUser) {
      setLocalTypes((current) => withTypeDefault(current, assetType.type, "transfer", null));
      setTypeError(t("handover.allocator.receiverRequired"));
      return;
    }

    const previous = localTypes;
    setLocalTypes(withTypeDefault(localTypes, assetType.type, nextAction, nextUser));
    setTypeError(null);
    setSavingType(true);
    try {
      const payload = await apiRequest<{ asset_type: HandoverAssetType; confirm_version: number }>(
        handoverAssetTypePath(scope.surface, scope.taskId, scope.appKey, assetType.type),
        {
          method: "PATCH",
          body: {
            default_action: nextAction,
            default_to_user_id: nextAction === "transfer" ? (nextUser?.user_id ?? null) : null,
          },
        },
      );
      setLocalTypes((current) => replaceAssetType(current, payload.asset_type));
      onActionUpdated?.({
        asset_types: replaceAssetType(localTypes, payload.asset_type),
        confirm_version: payload.confirm_version,
      });
    } catch (error) {
      setLocalTypes(previous);
      const reason = apiErrorReason(error);
      if (reason === "snapshot_stale") {
        handleSnapshotStale();
      } else {
        setTypeError((error as Error).message);
      }
    } finally {
      setSavingType(false);
    }
  };

  const applyOverridesSaved = (
    assetType: HandoverAssetType,
    result: { override_count: number; confirm_version: number; overrides_version: number },
  ) => {
    setLocalTypes((current) => withOverrideCount(current, assetType.type, result.override_count));
    onActionUpdated?.({
      confirm_version: result.confirm_version,
      overrides_version: result.overrides_version,
    });
  };

  return {
    types: localTypes,
    typeError,
    savingType,
    snapshotEpoch,
    expandedType,
    toggleExpanded: (type: string) => setExpandedType((current) => (current === type ? null : type)),
    counts: countArrangedAssetTypes(localTypes),
    patchType,
    handleSnapshotStale,
    setDetailsBusy,
    applyOverridesSaved,
  };
}
