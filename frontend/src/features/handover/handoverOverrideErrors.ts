/** 资产 override 请求的快照过期错误判定与状态切换。 */

import { apiErrorReason } from "../../lib/apiErrorReason";

interface SnapshotStaleActions {
  message: string;
  setError: (error: string | null) => void;
  resetLocalOverrideState: () => void;
  onSnapshotStale?: () => void;
}

export function handleSnapshotStaleError(error: unknown, actions: SnapshotStaleActions) {
  const reason = apiErrorReason(error);
  if (reason !== "snapshot_stale") {
    return { handled: false, reason };
  }
  actions.setError(actions.message);
  actions.resetLocalOverrideState();
  actions.onSnapshotStale?.();
  return { handled: true, reason };
}
