import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useI18n } from "../../i18n/I18nProvider";
import type { HandoverAction } from "../../lib/domain";
import { removeActionSnapshotQueries, type ActionSnapshotScope } from "./actionSnapshotCache";
import { classifyActionError } from "./handoverActionPanelModel";

export function useHandoverActionFailure({
  scope,
  action,
  onTaskRefresh,
}: {
  scope: ActionSnapshotScope;
  action: HandoverAction;
  onTaskRefresh: () => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [allocatorBusy, setAllocatorBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
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
    setAllocatorBusy(false);
    setAllocatorResetKey((key) => key + 1);
    removeActionSnapshotQueries(queryClient, scope);
    setBanner(t("handover.portal.detail.snapshotStale"));
    onTaskRefresh();
  };

  // snapshot_stale / confirm_version_stale 专管（清本地态 / 阻塞确认），其余 reason 统一关闭确认后落 banner
  const handleActionFailure = (error: Error, closeConfirm: () => void) => {
    const effect = classifyActionError(error);
    if (effect.kind === "snapshot_stale") {
      closeConfirm();
      handleSnapshotStale();
      return;
    }
    closeConfirm();
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

  return {
    banner,
    setBanner,
    allocatorBusy,
    setAllocatorBusy,
    allocatorResetKey,
    blockedConfirmVersion,
    handleSnapshotStale,
    handleActionFailure,
  };
}
