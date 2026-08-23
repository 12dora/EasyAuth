import type { QueryClient } from "@tanstack/react-query";

import type { HandoverSurface } from "./surface";

export interface ActionSnapshotScope {
  surface: HandoverSurface;
  taskId: number | string;
  appKey: string;
}

export function overridesQueryKey(scope: ActionSnapshotScope, assetType: string, snapshotEpoch: number) {
  return ["handover", "overrides", scope.surface, String(scope.taskId), scope.appKey, assetType, snapshotEpoch] as const;
}

export function assetItemsQueryKey(
  scope: ActionSnapshotScope,
  assetType: string,
  snapshotEpoch: number,
  page: number,
  search: string,
) {
  return [
    "handover",
    "items",
    scope.surface,
    String(scope.taskId),
    scope.appKey,
    assetType,
    snapshotEpoch,
    page,
    search,
  ] as const;
}

/** 412 snapshot_stale 后丢弃该 action 名下全部 items/overrides 缓存, 避免旧快照被复用。 */
export function removeActionSnapshotQueries(queryClient: QueryClient, scope: ActionSnapshotScope): void {
  void queryClient.removeQueries({
    predicate: (query) => {
      const key = query.queryKey;
      return (
        key[0] === "handover" &&
        (key[1] === "items" || key[1] === "overrides") &&
        key[2] === scope.surface &&
        key[3] === String(scope.taskId) &&
        key[4] === scope.appKey
      );
    },
  });
}
