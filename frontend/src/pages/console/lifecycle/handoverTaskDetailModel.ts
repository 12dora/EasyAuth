import type {
  HandoverGrantItemRow,
  HandoverTaskDetail,
  OnboardingTemplateRow,
  TransferGrantDiffEntry,
  TransferPlanItem,
} from "../../../lib/domain";
import type { AppShellOutletContext } from "../../../components/AppShell";
import type { Translator } from "../../../lib/status";
import { handoverKindLabel, type ParsedGrantKey } from "./lifecycleLabels";

const OPEN_TASK_STATUSES = new Set(["pending", "in_progress"]);
const ACTIONABLE_STATUSES = new Set(["pending", "previewed", "failed"]);

export function isOpenTask(task: HandoverTaskDetail | undefined): boolean {
  return Boolean(task && OPEN_TASK_STATUSES.has(task.status));
}

export function hasActionableApps(task: HandoverTaskDetail | undefined): boolean {
  return Boolean(task?.actions.some((action) => ACTIONABLE_STATUSES.has(action.status)));
}

/** executing / async_pending 期间轮询详情, 其余状态停轮询。 */
export function shouldPollTaskDetail(task: HandoverTaskDetail | undefined): number | false {
  if (!task) return false;
  return task.actions.some((a) => a.status === "executing" || a.status === "async_pending") ? 3000 : false;
}

export function selectionFromEntries(entries: TransferGrantDiffEntry[]): Record<string, boolean> {
  return Object.fromEntries(entries.map((entry) => [entry.key, entry.selected !== false]));
}

export function checkedKeys(selection: Record<string, boolean>): string[] {
  return Object.keys(selection).filter((key) => selection[key]);
}

export function transferPlanVersion(plan: TransferPlanItem | null | undefined): string {
  if (!plan) {
    return "none";
  }
  return String(plan.revision);
}

/** 差异条目只有 key; 用交接权限清单 + 模板项把 key 映射回业务名称。 */
export function buildGrantNameMap(
  grantItems: HandoverGrantItemRow[],
  templates: OnboardingTemplateRow[],
): Map<string, string> {
  const nameMap = new Map<string, string>();
  for (const item of grantItems) {
    nameMap.set(`${item.app_key}:${item.kind}:${item.key}`, item.name);
  }
  for (const template of templates) {
    for (const item of template.items) {
      nameMap.set(`${item.app_key}:${item.kind}:${item.key}`, item.name);
    }
  }
  return nameMap;
}

export function grantNameMapKey(parsed: ParsedGrantKey): string {
  return parsed.kind === "permission"
    ? `${parsed.appKey}:${parsed.kind}:${parsed.key}:${parsed.scopeKey}`
    : `${parsed.appKey}:${parsed.kind}:${parsed.key}`;
}

/** 差异三栏条目; 后端可能省略空数组字段。 */
export function transferDiffEntries(plan: TransferPlanItem): {
  revoke: TransferGrantDiffEntry[];
  add: TransferGrantDiffEntry[];
  keep: TransferGrantDiffEntry[];
} {
  return {
    revoke: plan.grant_diff.revoke ?? [],
    add: plan.grant_diff.add ?? [],
    keep: plan.grant_diff.keep ?? [],
  };
}

export function taskSubjectName(task: HandoverTaskDetail | undefined): string {
  return task ? task.subject.name || task.subject.user_id : "";
}

export function taskDetailTitle(t: Translator, task: HandoverTaskDetail | undefined, subjectName: string): string {
  return task ? `${handoverKindLabel(t, task.kind)} · ${subjectName}` : "-";
}

/** 控制台超管与本地管理员两种身份取自 AppShell outlet。 */
export function consoleViewerFlags(outlet: AppShellOutletContext | null): {
  isSuperuser: boolean;
  isLocalAdmin: boolean;
} {
  return {
    isSuperuser: outlet?.isSuperuser === true,
    isLocalAdmin: (outlet?.currentUserId ?? "").startsWith("local-admin:"),
  };
}
