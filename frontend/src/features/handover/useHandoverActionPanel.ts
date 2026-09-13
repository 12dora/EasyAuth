import { useState } from "react";

import type { HandoverAction } from "../../lib/domain";
import type { ActionSnapshotScope } from "./actionSnapshotCache";
import { useHandoverActionFailure } from "./useHandoverActionFailure";
import { useHandoverActionMutations } from "./useHandoverActionMutations";

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
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [skipOpen, setSkipOpen] = useState(false);
  const [asyncAbandonOpen, setAsyncAbandonOpen] = useState(false);
  const closeConfirm = () => setConfirmOpen(false);
  const closeSkip = () => setSkipOpen(false);
  const closeAsyncAbandon = () => setAsyncAbandonOpen(false);

  const failure = useHandoverActionFailure({ scope, action, onTaskRefresh });
  const handleSnapshotStale = () => {
    closeConfirm();
    failure.handleSnapshotStale();
  };
  const mutations = useHandoverActionMutations({
    scope,
    action,
    onTaskRefresh,
    onActionReplace,
    handleActionFailure: failure.handleActionFailure,
    closeConfirm,
    closeSkip,
    closeAsyncAbandon,
    setBanner: failure.setBanner,
  });

  // action 级互斥锁：grant_receiver PATCH 与执行/预演/分配不得竞态（§4 confirm_version）
  const grantBusy = mutations.grantReceiverMutation.isPending;
  const actionMutationLock =
    grantBusy ||
    failure.allocatorBusy ||
    mutations.previewMutation.isPending ||
    mutations.executeMutation.isPending ||
    failure.blockedConfirmVersion !== null;

  return {
    banner: failure.banner,
    grantBusy,
    actionMutationLock,
    allocatorResetKey: failure.allocatorResetKey,
    setAllocatorBusy: failure.setAllocatorBusy,
    handleSnapshotStale,
    confirmOpen,
    openConfirm: () => setConfirmOpen(true),
    closeConfirm,
    skipOpen,
    openSkip: () => setSkipOpen(true),
    closeSkip,
    skipReason: mutations.skipReason,
    setSkipReason: mutations.setSkipReason,
    asyncAbandonOpen,
    openAsyncAbandon: () => setAsyncAbandonOpen(true),
    closeAsyncAbandon,
    asyncOutcome: mutations.asyncOutcome,
    setAsyncOutcome: mutations.setAsyncOutcome,
    asyncReason: mutations.asyncReason,
    setAsyncReason: mutations.setAsyncReason,
    rawError: mutations.rawError,
    loadRawError: mutations.loadRawError,
    previewMutation: mutations.previewMutation,
    executeMutation: mutations.executeMutation,
    retryMutation: mutations.retryMutation,
    skipMutation: mutations.skipMutation,
    grantReceiverMutation: mutations.grantReceiverMutation,
    asyncAbandonMutation: mutations.asyncAbandonMutation,
    pollTick: mutations.pollTick,
  };
}
