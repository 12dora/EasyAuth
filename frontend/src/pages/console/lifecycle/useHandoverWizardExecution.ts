import { useEffect, useState } from "react";

import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type { HandoverAction, HandoverActionPayload, HandoverTaskDetail, HandoverUserRef } from "../../../lib/domain";
import {
  allActionsPreviewed,
  executeStateFromStatus,
  type WizardExecuteState,
} from "./handoverWizardModel";
import type { HandoverWizardStepId } from "./handoverWizardController";

export interface HandoverWizardExecutionOptions {
  task: HandoverTaskDetail;
  step: HandoverWizardStepId;
  selectedApps: HandoverAction[];
  invalidateDetail: () => void;
}

/** 向导「预演与分配」「执行」两段的运行时状态: 逐应用预演、接收人改派与串行执行。 */
export function useHandoverWizardExecution({
  task,
  step,
  selectedApps,
  invalidateDetail,
}: HandoverWizardExecutionOptions) {
  const [localActions, setLocalActions] = useState<Record<string, HandoverAction>>(() =>
    Object.fromEntries(task.actions.map((action) => [action.app_key, action])),
  );
  const [previewed, setPreviewed] = useState<Record<string, boolean>>({});
  const [executeState, setExecuteState] = useState<Record<string, WizardExecuteState>>({});
  const [isExecuting, setIsExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runPreview = async (appKey: string) => {
    setError(null);
    try {
      const payload = await apiRequest<HandoverActionPayload>(
        `/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${appKey}/preview`,
        { method: "POST", body: {} },
      );
      setLocalActions((current) => ({ ...current, [appKey]: payload.action }));
      setPreviewed((current) => ({ ...current, [appKey]: true }));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => {
    if (step !== "allocate") {
      return;
    }
    let cancelled = false;
    const run = async () => {
      for (const action of selectedApps) {
        if (cancelled || previewed[action.app_key] || localActions[action.app_key]?.status === "previewed") {
          if (localActions[action.app_key]?.status === "previewed") {
            setPreviewed((current) => ({ ...current, [action.app_key]: true }));
          }
          continue;
        }
        await runPreview(action.app_key);
      }
      if (!cancelled) {
        invalidateDetail();
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  const allPreviewed = allActionsPreviewed(selectedApps, previewed, localActions);

  const setGrantReceiver = async (action: HandoverAction, user: HandoverUserRef | null) => {
    const payload = await apiRequest<HandoverActionPayload>(
      `/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${action.app_key}`,
      { method: "PATCH", body: { grant_receiver_user_id: user?.user_id ?? null } },
    );
    setLocalActions((s) => ({ ...s, [action.app_key]: payload.action }));
    setPreviewed((s) => ({ ...s, [action.app_key]: false }));
  };

  const applyAllocatorPatch = (
    action: HandoverAction,
    patch: { asset_types?: HandoverAction["asset_types"]; confirm_version?: number; overrides_version?: number },
  ) => {
    setLocalActions((s) => ({
      ...s,
      [action.app_key]: {
        ...action,
        asset_types: patch.asset_types ?? action.asset_types,
        confirm_version: patch.confirm_version ?? action.confirm_version,
        overrides_version: patch.overrides_version ?? action.overrides_version,
      },
    }));
  };

  const runExecute = async () => {
    if (isExecuting || !allPreviewed) {
      return;
    }
    setIsExecuting(true);
    for (const action of selectedApps) {
      const current = localActions[action.app_key] ?? action;
      setExecuteState((s) => ({ ...s, [action.app_key]: "running" }));
      try {
        const operation = current.status === "failed" ? "retry" : "execute";
        const payload = await apiRequest<HandoverActionPayload>(
          `/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${action.app_key}/${operation}`,
          {
            method: "POST",
            body: operation === "execute" ? { confirm_version: current.confirm_version } : ({} as JsonObject),
          },
        );
        setLocalActions((s) => ({ ...s, [action.app_key]: payload.action }));
        setExecuteState((s) => ({ ...s, [action.app_key]: executeStateFromStatus(payload.action.status) }));
      } catch (err) {
        setExecuteState((s) => ({ ...s, [action.app_key]: "failed" }));
        setError((err as Error).message);
      }
      invalidateDetail();
    }
    setIsExecuting(false);
  };

  return {
    localActions,
    executeState,
    isExecuting,
    error,
    allPreviewed,
    allExecuted: selectedApps.length > 0 && selectedApps.every((a) => executeState[a.app_key] === "done"),
    runPreview,
    runExecute,
    setGrantReceiver,
    applyAllocatorPatch,
  };
}
