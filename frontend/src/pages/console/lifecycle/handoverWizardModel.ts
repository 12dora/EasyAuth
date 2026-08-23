import type { HandoverAction, HandoverGrantItemRow, HandoverTaskDetail } from "../../../lib/domain";
import { canSelectActionForWizard, type HandoverWizardStepId } from "./handoverWizardController";

const ACTIONABLE_STATUSES = new Set(["pending", "previewed", "failed"]);

export function isActionableStatus(status: string): boolean {
  return ACTIONABLE_STATUSES.has(status);
}

/** 向导只处理可操作 + blocked 的应用; blocked 仅展示不可勾选。 */
export function wizardBatchActions(task: HandoverTaskDetail): HandoverAction[] {
  return task.actions.filter((action) => isActionableStatus(action.status) || action.status === "blocked");
}

export function initialWizardSelection(batchActions: HandoverAction[]): Record<string, boolean> {
  return Object.fromEntries(
    batchActions.map((action) => [
      action.app_key,
      canSelectActionForWizard(action) && isActionableStatus(action.status),
    ]),
  );
}

export function wizardSelectedApps(
  batchActions: HandoverAction[],
  selected: Record<string, boolean>,
): HandoverAction[] {
  return batchActions.filter((action) => selected[action.app_key] && canSelectActionForWizard(action));
}

export function wizardBlockedCount(batchActions: HandoverAction[]): number {
  return batchActions.filter((action) => action.status === "blocked").length;
}

export type WizardExecuteState = "running" | "done" | "failed" | "async_pending";

export function executeStateFromStatus(status: HandoverAction["status"]): WizardExecuteState {
  if (status === "done") {
    return "done";
  }
  if (status === "async_pending") {
    return "async_pending";
  }
  return "failed";
}

export function isActionPreviewed(
  action: HandoverAction,
  previewed: Record<string, boolean>,
  localActions: Record<string, HandoverAction>,
): boolean {
  return Boolean(previewed[action.app_key]) || localActions[action.app_key]?.status === "previewed";
}

export function allActionsPreviewed(
  selectedApps: HandoverAction[],
  previewed: Record<string, boolean>,
  localActions: Record<string, HandoverAction>,
): boolean {
  return (
    selectedApps.length > 0 &&
    selectedApps.every((action) => isActionPreviewed(action, previewed, localActions))
  );
}

/** 仅下发选中应用下、仍 pending 且勾选状态与服务端不一致的授权条目。 */
export function changedGrantSelections(
  grantItems: HandoverGrantItemRow[],
  selectedApps: HandoverAction[],
  grantSelection: Record<number, boolean>,
): { id: number; selected: boolean }[] {
  return grantItems
    .filter((item) => item.status === "pending" && selectedApps.some((a) => a.app_key === item.app_key))
    .map((item) => ({ id: item.id, selected: grantSelection[item.id] ?? item.selected, was: item.selected }))
    .filter((item) => item.was !== item.selected)
    .map((item) => ({ id: item.id, selected: item.selected }));
}

export function mergeGrantSelection(
  current: Record<number, boolean>,
  grantItems: HandoverGrantItemRow[],
): Record<number, boolean> {
  const next = { ...current };
  for (const item of grantItems) {
    if (!(item.id in next)) {
      next[item.id] = item.selected;
    }
  }
  return next;
}

export function groupGrantItemsByApp(
  apps: HandoverAction[],
  items: HandoverGrantItemRow[],
): { action: HandoverAction; items: HandoverGrantItemRow[] }[] {
  return apps
    .map((action) => ({ action, items: items.filter((item) => item.app_key === action.app_key) }))
    .filter((group) => group.items.length > 0);
}

export interface WizardNextGate {
  step: HandoverWizardStepId;
  selectedCount: number;
  grantsLoading: boolean;
  grantsFailed: boolean;
  allPreviewed: boolean;
  isSaving: boolean;
  isExecuting: boolean;
}

/** 「下一步」禁用条件: 每段各自的准入 + 全局保存/执行中。 */
export function wizardNextDisabled(gate: WizardNextGate): boolean {
  return (
    (gate.step === "apps" && gate.selectedCount === 0) ||
    (gate.step === "grants" && (gate.grantsLoading || gate.grantsFailed)) ||
    (gate.step === "allocate" && !gate.allPreviewed) ||
    gate.isSaving ||
    gate.isExecuting
  );
}

/** 非 offboard 前进跳过授权段，后退也必须跳过，避免落在禁用的「授权」步。 */
export function wizardStepBack(step: HandoverWizardStepId, includeGrants: boolean): HandoverWizardStepId | null {
  if (step === "grants" || (step === "allocate" && !includeGrants)) {
    return "apps";
  }
  return null;
}
