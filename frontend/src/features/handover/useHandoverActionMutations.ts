import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest } from "../../lib/api";
import type { HandoverAction, HandoverActionPayload } from "../../lib/domain";
import type { ActionSnapshotScope } from "./actionSnapshotCache";
import { handoverActionPath } from "./surface";

interface MutationHost {
  scope: ActionSnapshotScope;
  action: HandoverAction;
  onTaskRefresh: () => void;
  onActionReplace: (action: HandoverAction) => void;
  handleActionFailure: (error: Error, closeConfirm: () => void) => void;
  closeConfirm: () => void;
  closeSkip: () => void;
  closeAsyncAbandon: () => void;
  setBanner: (banner: string | null) => void;
}

export function useHandoverActionMutations(host: MutationHost) {
  const queryClient = useQueryClient();
  const [skipReason, setSkipReason] = useState("");
  const [asyncOutcome, setAsyncOutcome] = useState<"done" | "failed">("done");
  const [asyncReason, setAsyncReason] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);
  const actionUrl = (suffix = "") =>
    handoverActionPath(host.scope.surface, host.scope.taskId, host.scope.appKey, suffix);
  const primary = useHandoverPrimaryMutations(host, actionUrl);
  const followup = useHandoverFollowupMutations(host, actionUrl, {
    skipReason,
    setSkipReason,
    asyncOutcome,
    asyncReason,
    setAsyncReason,
  });

  return {
    skipReason,
    setSkipReason,
    asyncOutcome,
    setAsyncOutcome,
    asyncReason,
    setAsyncReason,
    rawError,
    loadRawError: async () => {
      const payload = await apiRequest<{ last_error_raw: string }>(
        handoverActionPath("console", host.scope.taskId, host.scope.appKey, "errors/raw"),
      );
      setRawError(payload.last_error_raw);
    },
    ...primary,
    ...followup,
    pollTick: () => {
      void queryClient.invalidateQueries({
        queryKey: ["handover", "task", host.scope.surface, String(host.scope.taskId)],
      });
      host.onTaskRefresh();
    },
  };
}

function useHandoverPrimaryMutations(host: MutationHost, actionUrl: (suffix?: string) => string) {
  const { action, closeConfirm, handleActionFailure, onActionReplace, onTaskRefresh, setBanner } = host;
  const previewMutation = useMutation({
    mutationFn: () => apiRequest<HandoverActionPayload>(actionUrl("preview"), { method: "POST", body: {} }),
    onSuccess: (payload) => {
      setBanner(null);
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => {
      handleActionFailure(error, closeConfirm);
    },
  });
  const executeMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(actionUrl("execute"), {
        method: "POST",
        body: { confirm_version: action.confirm_version },
      }),
    onSuccess: (payload) => {
      closeConfirm();
      setBanner(null);
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => {
      handleActionFailure(error, closeConfirm);
    },
  });
  return { previewMutation, executeMutation };
}

function useHandoverFollowupMutations(
  host: MutationHost,
  actionUrl: (suffix?: string) => string,
  dialog: {
    skipReason: string;
    setSkipReason: (reason: string) => void;
    asyncOutcome: "done" | "failed";
    asyncReason: string;
    setAsyncReason: (reason: string) => void;
  },
) {
  const { closeAsyncAbandon, closeSkip, onActionReplace, onTaskRefresh, setBanner } = host;
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
        body: { reason: dialog.skipReason.trim() },
      }),
    onSuccess: (payload) => {
      closeSkip();
      dialog.setSkipReason("");
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
          outcome: dialog.asyncOutcome,
          reason: dialog.asyncReason.trim(),
          summary: null,
        },
      }),
    onSuccess: (payload) => {
      closeAsyncAbandon();
      dialog.setAsyncReason("");
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });
  return { retryMutation, skipMutation, grantReceiverMutation, asyncAbandonMutation };
}
