import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { HandoverAction, HandoverActionPayload } from "../../lib/domain";
import { removeActionSnapshotQueries, type ActionSnapshotScope } from "./actionSnapshotCache";
import { classifyActionError } from "./handoverActionPanelModel";
import { handoverActionPath } from "./surface";

export interface HandoverActionPanelOptions {
  scope: ActionSnapshotScope;
  action: HandoverAction;
  onTaskRefresh: () => void;
  onActionReplace: (action: HandoverAction) => void;
}

/** 单个应用交接卡的本地态、六个 action 级 mutation 与错误路由。 */
export function useHandoverActionPanel({
  scope,
  action,
  onTaskRefresh,
  onActionReplace,
}: HandoverActionPanelOptions) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [allocatorBusy, setAllocatorBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [skipOpen, setSkipOpen] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);
  const [asyncAbandonOpen, setAsyncAbandonOpen] = useState(false);
  const [asyncOutcome, setAsyncOutcome] = useState<"done" | "failed">("done");
  const [asyncReason, setAsyncReason] = useState("");
  /** 412 后强制 remount 分配器，清掉未保存 drafts / 展开态 */
  const [allocatorResetKey, setAllocatorResetKey] = useState(0);
  /** 409 confirm_version_stale：关闭确认并阻塞到新 confirm_version 装入 */
  const [blockedConfirmVersion, setBlockedConfirmVersion] = useState<number | null>(null);

  useEffect(() => {
    if (blockedConfirmVersion !== null && action.confirm_version !== blockedConfirmVersion) {
      setBlockedConfirmVersion(null);
    }
  }, [action.confirm_version, blockedConfirmVersion]);

  const handleSnapshotStale = () => {
    setConfirmOpen(false);
    setAllocatorBusy(false);
    setAllocatorResetKey((key) => key + 1);
    removeActionSnapshotQueries(queryClient, scope);
    setBanner(t("handover.portal.detail.snapshotStale"));
    onTaskRefresh();
  };

  // snapshot_stale / confirm_version_stale 专管（清本地态 / 阻塞确认），其余 reason 统一关闭确认后落 banner
  const handleActionFailure = (error: Error) => {
    const effect = classifyActionError(error);
    if (effect.kind === "snapshot_stale") {
      handleSnapshotStale();
      return;
    }
    setConfirmOpen(false);
    if (effect.kind === "confirm_version_stale") {
      setBanner(t("handover.portal.detail.confirmVersionStale"));
      setBlockedConfirmVersion(action.confirm_version);
      onTaskRefresh();
      return;
    }
    if (effect.kind === "downstream_locked") {
      setBanner(t("handover.portal.detail.downstreamLocked"));
      onTaskRefresh();
      return;
    }
    if (effect.kind === "payload_too_large") {
      setBanner(t("handover.portal.detail.payloadTooLarge"));
      onTaskRefresh();
      return;
    }
    setBanner(effect.message);
  };

  const actionUrl = (suffix = "") => handoverActionPath(scope.surface, scope.taskId, scope.appKey, suffix);

  const previewMutation = useMutation({
    mutationFn: () => apiRequest<HandoverActionPayload>(actionUrl("preview"), { method: "POST", body: {} }),
    onSuccess: (payload) => {
      setBanner(null);
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => {
      handleActionFailure(error);
    },
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(actionUrl("execute"), {
        method: "POST",
        body: { confirm_version: action.confirm_version },
      }),
    onSuccess: (payload) => {
      setConfirmOpen(false);
      setBanner(null);
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => {
      handleActionFailure(error);
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => apiRequest<HandoverActionPayload>(actionUrl("retry"), { method: "POST", body: {} }),
    onSuccess: (payload) => {
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const skipMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(actionUrl("skip"), {
        method: "POST",
        body: { reason: skipReason.trim() },
      }),
    onSuccess: (payload) => {
      setSkipOpen(false);
      setSkipReason("");
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const grantReceiverMutation = useMutation({
    mutationFn: (userId: string | null) =>
      apiRequest<HandoverActionPayload>(actionUrl(), {
        method: "PATCH",
        body: { grant_receiver_user_id: userId },
      }),
    onSuccess: (payload) => {
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const asyncAbandonMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(actionUrl("async-abandon"), {
        method: "POST",
        body: {
          outcome: asyncOutcome,
          reason: asyncReason.trim(),
          summary: null,
        },
      }),
    onSuccess: (payload) => {
      setAsyncAbandonOpen(false);
      setAsyncReason("");
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  // action 级互斥锁：grant_receiver PATCH 与执行/预演/分配不得竞态（§4 confirm_version）
  const grantBusy = grantReceiverMutation.isPending;
  const actionMutationLock =
    grantBusy ||
    allocatorBusy ||
    previewMutation.isPending ||
    executeMutation.isPending ||
    blockedConfirmVersion !== null;

  return {
    banner,
    grantBusy,
    actionMutationLock,
    allocatorResetKey,
    setAllocatorBusy,
    handleSnapshotStale,
    confirmOpen,
    openConfirm: () => setConfirmOpen(true),
    closeConfirm: () => setConfirmOpen(false),
    skipOpen,
    openSkip: () => setSkipOpen(true),
    closeSkip: () => setSkipOpen(false),
    skipReason,
    setSkipReason,
    asyncAbandonOpen,
    openAsyncAbandon: () => setAsyncAbandonOpen(true),
    closeAsyncAbandon: () => setAsyncAbandonOpen(false),
    asyncOutcome,
    setAsyncOutcome,
    asyncReason,
    setAsyncReason,
    rawError,
    loadRawError: async () => {
      const payload = await apiRequest<{ last_error_raw: string }>(
        handoverActionPath("console", scope.taskId, scope.appKey, "errors/raw"),
      );
      setRawError(payload.last_error_raw);
    },
    previewMutation,
    executeMutation,
    retryMutation,
    skipMutation,
    grantReceiverMutation,
    asyncAbandonMutation,
    pollTick: () => {
      void queryClient.invalidateQueries({ queryKey: ["handover", "task", scope.surface, String(scope.taskId)] });
      onTaskRefresh();
    },
  };
}
