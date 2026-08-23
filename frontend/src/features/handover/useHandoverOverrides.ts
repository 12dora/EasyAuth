/** 交接资产 override 权威集合、草稿与保存请求的状态边界。 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import type { HandoverAssetType, HandoverOverridesPayload } from "../../lib/domain";
import { overridesQueryKey, type ActionSnapshotScope } from "./actionSnapshotCache";
import {
  buildOverridesBody,
  draftsFromOverrides,
  hasIncompleteTransferDraft,
  type DraftOverride,
} from "./assetAllocatorModel";
import { handleSnapshotStaleError } from "./handoverOverrideErrors";
import { handoverAssetTypePath } from "./surface";

interface HandoverOverridesOptions {
  scope: ActionSnapshotScope;
  assetType: HandoverAssetType;
  snapshotEpoch: number;
  onSaved: (result: { override_count: number; confirm_version: number; overrides_version: number }) => void;
  onBusyChange?: (busy: boolean) => void;
  onSnapshotStale?: () => void;
  setError: (error: string | null) => void;
}

export function useHandoverOverrides(options: HandoverOverridesOptions) {
  const { scope, assetType, snapshotEpoch, onBusyChange, onSnapshotStale, setError } = options;
  const { t } = useI18n();
  const [drafts, setDrafts] = useState<Record<string, DraftOverride>>({});
  const [loadedOverrides, setLoadedOverrides] = useState(false);
  const [overridesVersion, setOverridesVersion] = useState(0);
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
  }, [overridesQuery.data, setError]);

  const resetLocalOverrideState = useCallback(() => {
    setDrafts({});
    setLoadedOverrides(false);
    setOverridesVersion(0);
  }, []);

  useEffect(() => {
    if (!overridesQuery.error) {
      return;
    }
    setLoadedOverrides(false);
    const result = handleSnapshotStaleError(overridesQuery.error, {
      message: t("handover.portal.detail.snapshotStale"),
      setError,
      resetLocalOverrideState,
      onSnapshotStale,
    });
    if (!result.handled) {
      setError((overridesQuery.error as Error).message);
    }
  }, [onSnapshotStale, overridesQuery.error, resetLocalOverrideState, setError, t]);

  const draftList = Object.values(drafts);
  const incompleteTransferDraft = hasIncompleteTransferDraft(draftList);
  const saveMutation = useSaveOverrides(
    options,
    draftList,
    overridesVersion,
    resetLocalOverrideState,
    setOverridesVersion,
    overridesQuery.refetch,
  );

  useEffect(() => {
    onBusyChange?.(saveMutation.isPending || incompleteTransferDraft);
  }, [onBusyChange, saveMutation.isPending, incompleteTransferDraft]);

  const requestSave = () => {
    if (incompleteTransferDraft) {
      setError(t("handover.allocator.receiverRequired"));
      return;
    }
    saveMutation.mutate();
  };

  return {
    drafts,
    setDrafts,
    loadedOverrides,
    resetLocalOverrideState,
    incompleteTransferDraft,
    saving: saveMutation.isPending,
    isFetching: overridesQuery.isFetching,
    isError: overridesQuery.isError,
    overridesLoading: overridesQuery.isLoading && !overridesQuery.isError,
    overridesFailedBeforeLoad: overridesQuery.isError && !loadedOverrides,
    requestSave,
  };
}

function useSaveOverrides(
  options: HandoverOverridesOptions,
  draftList: DraftOverride[],
  overridesVersion: number,
  resetLocalOverrideState: () => void,
  setOverridesVersion: (version: number) => void,
  refetchOverrides: () => Promise<unknown>,
) {
  const { scope, assetType, snapshotEpoch, onSaved, onSnapshotStale, setError } = options;
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const basePath = handoverAssetTypePath(scope.surface, scope.taskId, scope.appKey, assetType.type);
  const overridesQueryKeyValue = overridesQueryKey(scope, assetType.type, snapshotEpoch);
  return useMutation({
    mutationFn: async () => {
      if (hasIncompleteTransferDraft(draftList)) {
        throw new Error(t("handover.allocator.receiverRequired"));
      }
      return apiRequest<SaveOverridesPayload>(`${basePath}/overrides`, {
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
      void queryClient.invalidateQueries({ queryKey: overridesQueryKeyValue });
    },
    onError: async (error: Error) => {
      if (apiErrorReason(error) === "overrides_version_stale") {
        setError(t("handover.allocator.overridesStale"));
        await refetchOverrides();
        return;
      }
      const result = handleSnapshotStaleError(error, {
        message: t("handover.portal.detail.snapshotStale"),
        setError,
        resetLocalOverrideState,
        onSnapshotStale,
      });
      if (!result.handled) {
        setError(error.message);
      }
    },
  });
}

interface SaveOverridesPayload {
  overrides_version: number;
  confirm_version: number;
  override_count: number;
  dropped_invalid: number;
}
