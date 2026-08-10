import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RefreshCcw } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useOutletContext, useParams } from "react-router-dom";

import type { AppShellOutletContext } from "../../../components/AppShell";
import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { Dialog } from "../../../components/Dialog";
import { Field, SelectInput, TextArea } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserSearchInput } from "../../../components/UserSelect";
import { PageState } from "../../../components/ui/PageState";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useToast } from "../../../components/ui/Toast";
import { HandoverActionPanel } from "../../../features/handover/HandoverActionPanel";
import { daysLeftTone } from "../../../features/handover/surface";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type {
  HandoverAction,
  HandoverGrantItemRow,
  HandoverTaskDetail,
  HandoverTaskPayload,
  HandoverTeamItemRow,
  OnboardingTemplateRow,
  TransferGrantDiffEntry,
  TransferPlanItem,
} from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import { HandoverWizard } from "./HandoverWizard";
import {
  handoverAssigneeStateLabel,
  handoverKindLabel,
  handoverTaskStatusLabel,
  handoverTaskStatusTone,
  parseGrantDiffKey,
  personStatusLabel,
  personStatusTone,
} from "./lifecycleLabels";

const OPEN_TASK_STATUSES = new Set(["pending", "in_progress"]);
const ACTIONABLE_STATUSES = new Set(["pending", "previewed", "failed"]);

export function HandoverTaskDetail() {
  const { t } = useI18n();
  const toast = useToast();
  const { taskId = "" } = useParams();
  const queryClient = useQueryClient();
  const outlet = useOutletContext<AppShellOutletContext | null>();
  const isSuperuser = outlet?.isSuperuser === true;
  const isLocalAdmin = (outlet?.currentUserId ?? "").startsWith("local-admin:");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deferOpen, setDeferOpen] = useState(false);
  const [deferReason, setDeferReason] = useState("");
  const detailQueryKey = ["console", "handover-task", taskId];
  const navigate = useNavigate();

  const taskQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => apiRequest<HandoverTaskPayload>(`/console/api/v1/lifecycle/handover-tasks/${taskId}`),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const task = query.state.data?.handover_task;
      if (!task) return false;
      return task.actions.some((a) => a.status === "executing" || a.status === "async_pending") ? 3000 : false;
    },
  });
  const task = taskQuery.data?.handover_task;
  const invalidateDetail = () => void queryClient.invalidateQueries({ queryKey: detailQueryKey });

  const replaceAction = (next: HandoverAction) => {
    queryClient.setQueryData<HandoverTaskPayload>(detailQueryKey, (current) => {
      if (!current?.handover_task) return current;
      return {
        handover_task: {
          ...current.handover_task,
          actions: current.handover_task.actions.map((a) => (a.app_key === next.app_key ? next : a)),
        },
      };
    });
  };

  const cancelMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>(`/console/api/v1/lifecycle/handover-tasks/${taskId}`, {
        method: "PATCH",
        body: { cancel: true } satisfies JsonObject,
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailQueryKey, payload);
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      setCancelConfirmOpen(false);
    },
    onError: (error: Error) => toast.error(t("handover.detail.cancelFailed"), error.message),
  });

  const deleteMutation = useMutation({
    mutationFn: () => apiRequest(`/console/api/v1/lifecycle/handover-tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      void navigate("/console/lifecycle/handover-tasks");
    },
    onError: (error: Error) => toast.error(t("handover.detail.deleteFailed"), error.message),
  });

  const claimMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>(`/console/api/v1/lifecycle/handover-tasks/${taskId}/claim`, {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailQueryKey, payload);
      invalidateDetail();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const deferMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>(`/console/api/v1/lifecycle/handover-tasks/${taskId}/escalation/defer`, {
        method: "POST",
        body: { reason: deferReason.trim() },
      }),
    onSuccess: (payload) => {
      queryClient.setQueryData(detailQueryKey, payload);
      setDeferOpen(false);
      setDeferReason("");
      invalidateDetail();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (taskQuery.error && !task) {
    return (
      <PageState
        tone="signal"
        title={t("handover.detail.loadFailed")}
        description={(taskQuery.error as Error).message}
        action={
          <Button icon={<RefreshCcw size={16} />} loading={taskQuery.isFetching} onClick={() => void taskQuery.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    );
  }

  const isOpenTask = Boolean(task && OPEN_TASK_STATUSES.has(task.status));
  const hasActionableApps = Boolean(task?.actions.some((action) => ACTIONABLE_STATUSES.has(action.status)));
  const subjectName = task ? task.subject.name || task.subject.user_id : "";
  const subjectStatus = task?.subject.status ?? "";
  const canDefer = Boolean(task && task.escalation.deferred_at == null && task.escalation.deadline != null);
  const canClaim = Boolean(task && task.assignee_state === "superuser_pool");

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={task ? `${handoverKindLabel(t, task.kind)} · ${subjectName}` : "-"}
        description={task?.reason || undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <ButtonLink to="/console/lifecycle/handover-tasks">{t("handover.detail.backToList")}</ButtonLink>
            {isOpenTask ? (
              <>
                <Button type="button" variant="ghost-danger" onClick={() => { cancelMutation.reset(); setCancelConfirmOpen(true); }}>
                  {t("handover.detail.cancelTask")}
                </Button>
                <Button type="button" variant="primary" icon={<ArrowRight size={16} />} disabled={!hasActionableApps} onClick={() => setWizardOpen(true)}>
                  {t("handover.continue")}
                </Button>
              </>
            ) : null}
            {task?.status === "cancelled" ? (
              <Button type="button" variant="ghost-danger" onClick={() => { deleteMutation.reset(); setDeleteConfirmOpen(true); }}>
                {t("handover.detail.deleteTask")}
              </Button>
            ) : null}
          </div>
        }
      />
      {taskQuery.error && task ? (
        <StatusBanner live="alert" tone="signal" title={t("handover.detail.loadFailed")} message={(taskQuery.error as Error).message} />
      ) : null}
      {task ? (
        <section className="space-y-6">
          <PanelSurface padding="lg" className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-ink">{t("handover.detail.subject")}</h2>
              <Badge tone={handoverTaskStatusTone(task.status)}>{handoverTaskStatusLabel(t, task.status)}</Badge>
            </div>
            <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
              <OverviewItem
                label={t("handover.detail.subject")}
                value={
                  <span className="inline-flex items-center gap-1.5">
                    {subjectName}
                    {subjectStatus ? <Badge tone={personStatusTone(subjectStatus)}>{personStatusLabel(t, subjectStatus)}</Badge> : null}
                  </span>
                }
              />
              <OverviewItem label={t("handover.list.column.kind")} value={handoverKindLabel(t, task.kind)} />
              <OverviewItem label={t("people.column.department")} value={task.subject.department || "-"} />
              <OverviewItem label={t("people.column.email")} value={task.subject.email || "-"} />
              <OverviewItem label={t("handover.detail.createdAt")} value={formatDateTime(task.created_at)} />
              <OverviewItem label={t("handover.detail.createdBy")} value={task.created_by || "-"} />
            </dl>
            {task.reason ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("handover.detail.reason")}: {task.reason}</p> : null}
          </PanelSurface>

          <PanelSurface padding="lg" className="space-y-3" data-testid="assignee-card">
            <h2 className="text-base font-semibold text-ink">{t("handover.console.assigneeCard")}</h2>
            <dl className="grid gap-2 text-body sm:grid-cols-2">
              <OverviewItem label={t("handover.console.assigneeCard")} value={task.assignee?.name || task.assignee?.user_id || "-"} />
              <OverviewItem label={t("handover.console.filter.assigneeState")} value={handoverAssigneeStateLabel(t, task.assignee_state)} />
              <OverviewItem label={t("handover.portal.detail.escalated")} value={String(task.escalation_level)} />
              <OverviewItem
                label={t("handover.console.escalationDeadline")}
                value={
                  task.escalation.deadline
                    ? `${formatDateTime(task.escalation.deadline)} · ${t("handover.console.daysLeft", { count: task.escalation.days_left ?? 0 })}`
                    : t("handover.portal.list.awaitingSuperuser")
                }
              />
            </dl>
            {task.escalation.days_left != null ? (
              <Badge tone={daysLeftTone(task.escalation.days_left)}>{t("handover.console.daysLeft", { count: task.escalation.days_left })}</Badge>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                disabled={!canDefer}
                onClick={() => setDeferOpen(true)}
                data-testid="defer-button"
              >
                {t("handover.console.defer")}
              </Button>
              {canClaim ? (
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  disabled={isLocalAdmin}
                  title={isLocalAdmin ? t("handover.console.claimDisabledLocalAdmin") : undefined}
                  loading={claimMutation.isPending}
                  onClick={() => claimMutation.mutate()}
                  data-testid="claim-button"
                >
                  {t("handover.console.claim")}
                </Button>
              ) : null}
            </div>
            {(task.escalation.defer_history?.length ?? 0) > 0 ? (
              <div className="space-y-1">
                <h3 className="text-caption font-semibold text-ink-soft">{t("handover.console.deferHistory")}</h3>
                <ul className="grid gap-1 text-caption text-ink-faint">
                  {task.escalation.defer_history.map((entry, index) => (
                    <li key={`${entry.at}-${index}`}>
                      L{entry.escalation_level} · {entry.actor_id} · {formatDateTime(entry.at)} · {entry.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </PanelSurface>

          <PanelSurface padding="lg" className="space-y-4">
            <h2 className="text-base font-semibold text-ink">{t("handover.detail.apps")}</h2>
            {task.actions.length === 0 ? (
              <p className="text-body leading-5 text-ink-soft">{t("handover.detail.appsEmpty")}</p>
            ) : (
              <ul className="grid gap-3">
                {task.actions.map((action) => (
                  <HandoverActionPanel
                    key={action.app_key}
                    surface="console"
                    task={task}
                    action={action}
                    isConsoleSuperuser={isSuperuser}
                    isLocalAdmin={isLocalAdmin}
                    onTaskRefresh={invalidateDetail}
                    onActionReplace={replaceAction}
                  />
                ))}
              </ul>
            )}
          </PanelSurface>

          {task.kind === "transfer" ? (
            <TransferGrantSection task={task} taskId={taskId} onChanged={invalidateDetail} canOperate={isOpenTask} />
          ) : null}
          {task.kind === "transfer" || task.team_items.length > 0 ? (
            <TeamAdjustSection task={task} taskId={taskId} onChanged={invalidateDetail} canOperate={isOpenTask} />
          ) : null}
        </section>
      ) : null}

      {wizardOpen && task ? <HandoverWizard task={task} onClose={() => setWizardOpen(false)} /> : null}

      {deferOpen ? (
        <Dialog
          title={t("handover.console.deferTitle")}
          size="sm"
          onClose={() => setDeferOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setDeferOpen(false)}>{t("common.cancel")}</Button>
              <Button
                type="button"
                variant="primary"
                disabled={deferReason.trim().length < 10}
                loading={deferMutation.isPending}
                onClick={() => deferMutation.mutate()}
              >
                {t("handover.console.deferConfirm")}
              </Button>
            </>
          }
        >
          <TextArea
            value={deferReason}
            aria-label={t("handover.console.deferReason")}
            onChange={(event) => setDeferReason(event.currentTarget.value)}
          />
        </Dialog>
      ) : null}

      {deleteConfirmOpen && task ? (
        <Dialog
          title={t("handover.detail.deleteTask")}
          size="sm"
          onClose={() => setDeleteConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setDeleteConfirmOpen(false)}>{t("common.cancel")}</Button>
              <Button type="button" variant="danger" loading={deleteMutation.isPending} disabled={deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>
                {t("handover.detail.deleteConfirm")}
              </Button>
            </>
          }
        >
          <p className="text-body leading-5 text-ink-soft">{t("handover.detail.deleteMessage", { name: subjectName })}</p>
        </Dialog>
      ) : null}
      {cancelConfirmOpen && task ? (
        <Dialog
          title={t("handover.detail.cancelTask")}
          size="sm"
          onClose={() => setCancelConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setCancelConfirmOpen(false)}>{t("common.cancel")}</Button>
              <Button type="button" variant="danger" loading={cancelMutation.isPending} disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
                {t("handover.detail.cancelConfirm")}
              </Button>
            </>
          }
        >
          <p className="text-body leading-5 text-ink-soft">{t("handover.detail.cancelMessage", { name: subjectName })}</p>
        </Dialog>
      ) : null}
    </>
  );
}

function OverviewItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

/** 转岗: 本人权限调整。选岗位模板 → 生成收回/新增/保留差异 → 勾选确认。 */
function TransferGrantSection({
  task,
  taskId,
  onChanged,
  canOperate,
}: {
  task: HandoverTaskDetail;
  taskId: string;
  onChanged: () => void;
  canOperate: boolean;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const plan = task.transfer_plan;
  const [templateId, setTemplateId] = useState(plan?.template_id ? String(plan.template_id) : "");
  const planVersion = transferPlanVersion(plan);
  const initializedPlanVersion = useRef(planVersion);
  const [revokeChecked, setRevokeChecked] = useState<Record<string, boolean>>(() =>
    selectionFromEntries(plan?.grant_diff.revoke ?? []),
  );
  const [addChecked, setAddChecked] = useState<Record<string, boolean>>(() =>
    selectionFromEntries(plan?.grant_diff.add ?? []),
  );

  const templatesQuery = useQuery({
    queryKey: ["console", "onboarding-templates"],
    queryFn: () => apiRequest<ListPayload<OnboardingTemplateRow>>("/console/api/v1/lifecycle/onboarding-templates"),
  });
  const templates = itemsFromPayload<OnboardingTemplateRow>(templatesQuery.data).filter((template) => template.is_active);

  // 差异条目只有 key; 用交接权限清单 + 模板项把 key 映射回业务名称。
  const grantItemsQuery = useQuery({
    queryKey: ["console", "handover-task", taskId, "grant-items"],
    queryFn: () => apiRequest<ListPayload<HandoverGrantItemRow>>(`/console/api/v1/lifecycle/handover-tasks/${taskId}/grant-items`),
  });
  const nameMap = new Map<string, string>();
  for (const item of itemsFromPayload<HandoverGrantItemRow>(grantItemsQuery.data)) {
    nameMap.set(`${item.app_key}:${item.kind}:${item.key}`, item.name);
  }
  for (const template of templates) {
    for (const item of template.items) {
      nameMap.set(`${item.app_key}:${item.kind}:${item.key}`, item.name);
    }
  }

  // 同一方案的详情 refetch 不覆盖本地 dirty 选择；仅方案内容实际变化时重新初始化。
  useEffect(() => {
    if (initializedPlanVersion.current === planVersion) {
      return;
    }
    initializedPlanVersion.current = planVersion;
    setRevokeChecked(selectionFromEntries(plan?.grant_diff.revoke ?? []));
    setAddChecked(selectionFromEntries(plan?.grant_diff.add ?? []));
  }, [plan, planVersion]);

  const buildMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ transfer_plan?: TransferPlanItem }>(`/console/api/v1/lifecycle/handover-tasks/${taskId}/grant-diff`, {
        method: "POST",
        body: { template_id: Number(templateId) } satisfies JsonObject,
      }),
    onSuccess: onChanged,
    onError: (error: Error) => {
      toast.error(t("handover.transfer.diffFailed"), error.message);
    },
  });
  const confirmMutation = useMutation({
    mutationFn: () =>
      apiRequest<{ transfer_plan?: TransferPlanItem }>(`/console/api/v1/lifecycle/handover-tasks/${taskId}/grant-diff/confirm`, {
        method: "POST",
        body: {
          revoke_keys: Object.keys(revokeChecked).filter((key) => revokeChecked[key]),
          add_keys: Object.keys(addChecked).filter((key) => addChecked[key]),
          plan_revision: plan?.revision ?? 0,
        } satisfies JsonObject,
      }),
    onSuccess: onChanged,
    onError: (error: Error) => {
      toast.error(t("handover.transfer.confirmFailed"), error.message);
    },
  });

  const revokeEntries = plan?.grant_diff.revoke ?? [];
  const addEntries = plan?.grant_diff.add ?? [];
  const keepEntries = plan?.grant_diff.keep ?? [];
  const confirmed = Boolean(plan?.confirmed_at);
  const readOnly = confirmed || !canOperate;

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("handover.transfer.grantTitle")}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("handover.transfer.grantHint")}</p>
      </div>
      {templatesQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("onboarding.templates.loadFailed")} message={(templatesQuery.error as Error).message} />
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        <div className="w-64">
          <Field label={t("handover.transfer.template")}>
            <SelectInput value={templateId} disabled={readOnly} onChange={(event) => setTemplateId(event.currentTarget.value)}>
              <option value="">{t("handover.transfer.templatePlaceholder")}</option>
              {templates.map((template) => (
                <option key={template.id} value={String(template.id)}>
                  {template.name}
                  {template.current_revision ? ` · r${template.current_revision}` : ""}
                </option>
              ))}
            </SelectInput>
          </Field>
        </div>
        <Button
          type="button"
          disabled={!templateId || readOnly || confirmMutation.isPending}
          loading={buildMutation.isPending}
          onClick={() => buildMutation.mutate()}
        >
          {t("handover.transfer.buildDiff")}
        </Button>
      </div>
      {plan ? (
        <div className="space-y-4">
          <p className="text-body leading-5 text-ink">
            {t("handover.transfer.diffSummary", {
              revoke: revokeEntries.length,
              add: addEntries.length,
              keep: keepEntries.length,
            })}
          </p>
          <p className="text-caption text-ink-faint">
            {t("handover.transfer.boundRevision", {
              template: plan.template_name || "-",
              revision: plan.template_revision ?? "-",
            })}
          </p>
          {confirmed ? (
            <div>
              <StatusBanner live="status" tone="evergreen" title={t("handover.transfer.confirmedAt", { time: formatDateTime(plan.confirmed_at) })} />
            </div>
          ) : null}
          <div className="grid gap-4 lg:grid-cols-3">
            <DiffGroup
              title={t("handover.transfer.revoke")}
              entries={revokeEntries}
              nameMap={nameMap}
              readOnly={readOnly}
              checked={revokeChecked}
              onToggle={(key, value) => setRevokeChecked((current) => ({ ...current, [key]: value }))}
            />
            <DiffGroup
              title={t("handover.transfer.add")}
              entries={addEntries}
              nameMap={nameMap}
              readOnly={readOnly}
              checked={addChecked}
              onToggle={(key, value) => setAddChecked((current) => ({ ...current, [key]: value }))}
            />
            <DiffGroup title={t("handover.transfer.keep")} entries={keepEntries} nameMap={nameMap} readOnly checked={null} />
          </div>
          {!readOnly ? (
            <Button
              type="button"
              variant="primary"
              disabled={buildMutation.isPending}
              loading={confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              {t("handover.transfer.confirm")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </PanelSurface>
  );
}

function selectionFromEntries(entries: TransferGrantDiffEntry[]): Record<string, boolean> {
  return Object.fromEntries(entries.map((entry) => [entry.key, entry.selected !== false]));
}

function transferPlanVersion(plan: TransferPlanItem | null | undefined): string {
  if (!plan) {
    return "none";
  }
  return String(plan.revision);
}

function DiffGroup({
  title,
  entries,
  nameMap,
  readOnly,
  checked,
  onToggle,
}: {
  title: string;
  entries: TransferGrantDiffEntry[];
  nameMap: Map<string, string>;
  readOnly: boolean;
  checked: Record<string, boolean> | null;
  onToggle?: (key: string, value: boolean) => void;
}) {
  const { t } = useI18n();
  return (
    <div className="space-y-2 rounded-[3px] border border-ink/10 bg-paper-soft p-3">
      <h3 className="text-body font-semibold text-ink">
        {title}
        <span className="ml-1.5 text-caption font-normal text-ink-faint">{entries.length}</span>
      </h3>
      {entries.length === 0 ? (
        <p className="text-caption text-ink-faint">{t("handover.transfer.emptyGroup")}</p>
      ) : (
        <ul className="grid gap-1.5">
          {entries.map((entry) => {
            const parsed = parseGrantDiffKey(entry.key);
            const mapKey =
              parsed.kind === "permission"
                ? `${parsed.appKey}:${parsed.kind}:${parsed.key}:${parsed.scopeKey}`
                : `${parsed.appKey}:${parsed.kind}:${parsed.key}`;
            const mappedName = entry.name || nameMap.get(mapKey);
            const kindLabel = parsed.kind === "group" ? t("handover.diff.kind.group") : t("handover.diff.kind.permission");
            const label = (
              <span className="flex min-w-0 flex-col gap-0.5">
                <span className="text-body text-ink">{mappedName || parsed.key || entry.key}</span>
                <span className="text-caption text-ink-faint">
                  {parsed.appKey}
                  {" · "}
                  {kindLabel}
                  {parsed.scopeKey ? ` · ${parsed.scopeKey}` : ""}
                </span>
              </span>
            );
            if (checked === null) {
              return <li key={entry.key}>{label}</li>;
            }
            return (
              <li key={entry.key}>
                <label className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    className="mt-1"
                    disabled={readOnly}
                    checked={checked[entry.key] ?? true}
                    onChange={(event) => onToggle?.(entry.key, event.currentTarget.checked)}
                  />
                  {label}
                </label>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** 团队调整: 每行指定接任负责人或停用团队, 提交即生效。 */
function TeamAdjustSection({
  task,
  taskId,
  onChanged,
  canOperate,
}: {
  task: HandoverTaskDetail;
  taskId: string;
  onChanged: () => void;
  canOperate: boolean;
}) {
  const { t } = useI18n();
  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-ink">{t("handover.team.title")}</h2>
        <p className="max-w-3xl text-body leading-5 text-ink-soft">{t("handover.team.hint")}</p>
      </div>
      {task.team_items.length === 0 ? (
        <p className="text-body leading-5 text-ink-soft">{t("handover.team.empty")}</p>
      ) : (
        <ul className="grid gap-2.5">
          {task.team_items.map((item) => (
            <TeamAdjustRow key={item.id} item={item} taskId={taskId} onChanged={onChanged} canOperate={canOperate} />
          ))}
        </ul>
      )}
    </PanelSurface>
  );
}

function TeamAdjustRow({
  item,
  taskId,
  onChanged,
  canOperate,
}: {
  item: HandoverTeamItemRow;
  taskId: string;
  onChanged: () => void;
  canOperate: boolean;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [action, setAction] = useState<"assign_leader" | "deactivate">(
    item.action === "deactivate" ? "deactivate" : "assign_leader",
  );
  const [successorId, setSuccessorId] = useState(item.to_user?.user_id ?? "");
  const applyMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/lifecycle/handover-tasks/${taskId}/team-items/${item.id}`, {
        method: "PATCH",
        body: {
          action,
          ...(action === "assign_leader" ? { to_user_id: successorId.trim() } : {}),
        } satisfies JsonObject,
      }),
    onSuccess: onChanged,
    onError: (error: Error) => {
      toast.error(t("handover.team.applyFailed"), error.message);
    },
  });

  if (item.status !== "pending") {
    const doneLabel =
      item.status === "skipped"
        ? t("handover.team.doneSkipped")
        : item.action === "deactivate"
          ? t("handover.team.doneDeactivated")
          : t("handover.team.doneAssigned", { name: item.to_user?.name || item.to_user?.user_id || "-" });
    return (
      <li className="flex flex-wrap items-center justify-between gap-3 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2.5">
        <strong className="text-body text-ink">{item.team_name}</strong>
        <span className="text-body text-ink-soft">{doneLabel}</span>
      </li>
    );
  }

  return (
    <li className="space-y-2.5 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <strong className="min-w-32 text-body text-ink">{item.team_name}</strong>
        <SelectInput
          aria-label={`${item.team_name} ${t("common.actions")}`}
          className="w-56"
          value={action}
          disabled={!canOperate}
          onChange={(event) => setAction(event.currentTarget.value as "assign_leader" | "deactivate")}
        >
          <option value="assign_leader">{t("handover.team.assignLeader")}</option>
          <option value="deactivate">{t("handover.team.deactivate")}</option>
        </SelectInput>
        {action === "assign_leader" ? (
          <div className="min-w-56 flex-1">
            {canOperate ? (
              <UserSearchInput
                value={successorId}
                aria-label={`${item.team_name} ${t("handover.team.successor")}`}
                onChange={setSuccessorId}
              />
            ) : (
              <span className="text-body text-ink-soft">{successorId || "-"}</span>
            )}
          </div>
        ) : null}
        <Button
          type="button"
          disabled={!canOperate || (action === "assign_leader" && !successorId.trim())}
          loading={applyMutation.isPending}
          onClick={() => applyMutation.mutate()}
        >
          {t("handover.team.apply")}
        </Button>
      </div>
    </li>
  );
}
