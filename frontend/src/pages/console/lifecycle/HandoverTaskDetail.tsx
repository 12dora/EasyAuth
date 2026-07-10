import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, RefreshCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { Dialog } from "../../../components/Dialog";
import { Field, SelectInput } from "../../../components/Field";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserSearchInput } from "../../../components/UserSelect";
import { PageState } from "../../../components/ui/PageState";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type {
  HandoverAppActionRow,
  HandoverGrantItemRow,
  HandoverTaskDetailItem,
  HandoverTaskPayload,
  HandoverTeamItemRow,
  OnboardingTemplateRow,
  TransferGrantDiffEntry,
  TransferPlanItem,
} from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import { HandoverWizard } from "./HandoverWizard";
import {
  handoverActionStatusLabel,
  handoverActionStatusTone,
  handoverActionSummary,
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
  const [wizardOpen, setWizardOpen] = useState(false);
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const detailQueryKey = ["console", "handover-task", taskId];
  const navigate = useNavigate();

  const taskQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => apiRequest<HandoverTaskPayload>(`/console/api/v1/lifecycle/handover-tasks/${taskId}`),
    enabled: Boolean(taskId),
  });
  const task = taskQuery.data?.handover_task;
  const invalidateDetail = () => void queryClient.invalidateQueries({ queryKey: detailQueryKey });

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
    onError: (error: Error) => {
      toast.error(t("handover.detail.cancelFailed"), error.message);
    },
  });

  const retryMutation = useMutation({
    mutationFn: (appKey: string) =>
      apiRequest(`/console/api/v1/lifecycle/handover-tasks/${taskId}/actions/${appKey}/retry`, {
        method: "POST",
        body: {},
      }),
    onSuccess: invalidateDetail,
    onError: (error: Error) => {
      toast.error(t("handover.card.retryFailed"), error.message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () =>
      apiRequest(`/console/api/v1/lifecycle/handover-tasks/${taskId}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["console", "handover-tasks"] });
      void navigate("/console/lifecycle/handover-tasks");
    },
    onError: (error: Error) => {
      toast.error(t("handover.detail.deleteFailed"), error.message);
    },
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
  const hasActionableApps = Boolean(task?.app_actions.some((action) => ACTIONABLE_STATUSES.has(action.status)));
  const subjectName = task ? task.subject.name || task.subject.user_id : "";

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
                <Button
                  type="button"
                  variant="ghost-danger"
                  onClick={() => {
                    cancelMutation.reset();
                    setCancelConfirmOpen(true);
                  }}
                >
                  {t("handover.detail.cancelTask")}
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  icon={<ArrowRight size={16} />}
                  disabled={!hasActionableApps}
                  onClick={() => setWizardOpen(true)}
                >
                  {t("handover.continue")}
                </Button>
              </>
            ) : null}
            {task?.status === "cancelled" ? (
              <Button
                type="button"
                variant="ghost-danger"
                onClick={() => {
                  deleteMutation.reset();
                  setDeleteConfirmOpen(true);
                }}
              >
                {t("handover.detail.deleteTask")}
              </Button>
            ) : null}
          </div>
        }
      />
      {taskQuery.error && task ? (
        <StatusBanner tone="signal" title={t("handover.detail.loadFailed")} message={(taskQuery.error as Error).message} />
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
                    <Badge tone={personStatusTone(task.subject.status)}>{personStatusLabel(t, task.subject.status)}</Badge>
                  </span>
                }
              />
              <OverviewItem label={t("handover.list.column.kind")} value={handoverKindLabel(t, task.kind)} />
              <OverviewItem label={t("people.column.department")} value={task.subject.department || "-"} />
              <OverviewItem label={t("people.column.email")} value={task.subject.email || "-"} />
              <OverviewItem label={t("handover.detail.createdAt")} value={formatDateTime(task.created_at)} />
              <OverviewItem label={t("handover.detail.createdBy")} value={task.created_by || "-"} />
            </dl>
            {task.reason ? (
              <p className="max-w-3xl text-body leading-5 text-ink-soft">
                {t("handover.detail.reason")}: {task.reason}
              </p>
            ) : null}
          </PanelSurface>
          <PanelSurface padding="lg" className="space-y-4">
            <h2 className="text-base font-semibold text-ink">{t("handover.detail.apps")}</h2>
            {task.app_actions.length === 0 ? (
              <p className="text-body leading-5 text-ink-soft">{t("handover.detail.appsEmpty")}</p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2">
                {task.app_actions.map((action) => (
                  <AppActionCard
                    key={action.app_key}
                    action={action}
                    canRetry={isOpenTask}
                    retryPending={retryMutation.isPending && retryMutation.variables === action.app_key}
                    onRetry={() => retryMutation.mutate(action.app_key)}
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
      {deleteConfirmOpen && task ? (
        <Dialog
          title={t("handover.detail.deleteTask")}
          size="sm"
          onClose={() => setDeleteConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setDeleteConfirmOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                loading={deleteMutation.isPending}
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate()}
              >
                {t("handover.detail.deleteConfirm")}
              </Button>
            </>
          }
        >
          <div className="grid gap-3">
            <p className="text-body leading-5 text-ink-soft">{t("handover.detail.deleteMessage", { name: subjectName })}</p>
          </div>
        </Dialog>
      ) : null}
      {cancelConfirmOpen && task ? (
        <Dialog
          title={t("handover.detail.cancelTask")}
          size="sm"
          onClose={() => setCancelConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setCancelConfirmOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                loading={cancelMutation.isPending}
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate()}
              >
                {t("handover.detail.cancelConfirm")}
              </Button>
            </>
          }
        >
          <div className="grid gap-3">
            <p className="text-body leading-5 text-ink-soft">{t("handover.detail.cancelMessage", { name: subjectName })}</p>
          </div>
        </Dialog>
      ) : null}
    </>
  );
}

function OverviewItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

function AppActionCard({
  action,
  canRetry,
  retryPending,
  onRetry,
}: {
  action: HandoverAppActionRow;
  canRetry: boolean;
  retryPending: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  return (
    <li className="flex flex-col gap-2 rounded-[3px] border border-ink/12 bg-paper-soft px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <strong className="text-body text-ink">{action.app_name || action.app_key}</strong>
        <Badge tone={handoverActionStatusTone(action.status)}>{handoverActionStatusLabel(t, action.status)}</Badge>
      </div>
      <p className="text-body leading-5 text-ink-soft">{handoverActionSummary(t, action)}</p>
      {action.status === "failed" || action.status === "async_pending" ? (
        <div className="flex flex-wrap items-center gap-2">
          {action.status === "failed" && action.last_error ? (
            <span className="text-caption leading-5 text-signal">{action.last_error}</span>
          ) : null}
          {canRetry ? (
            <Button size="sm" type="button" loading={retryPending} onClick={onRetry}>
              {t(action.status === "async_pending" ? "handover.card.checkStatus" : "handover.card.retry")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {action.attempts > 0 || action.last_error ? (
        <details className="text-caption text-ink-faint">
          <summary className="cursor-pointer">{t("handover.card.details")}</summary>
          <dl className="mt-1.5 grid gap-1">
            <div className="flex items-center justify-between gap-3">
              <dt>{t("handover.card.attempts")}</dt>
              <dd className="m-0 font-mono">{action.attempts}</dd>
            </div>
            {action.last_error ? (
              <div className="flex items-start justify-between gap-3">
                <dt className="shrink-0">{t("handover.card.lastError")}</dt>
                <dd className="m-0 min-w-0 break-all text-right">{action.last_error}</dd>
              </div>
            ) : null}
          </dl>
        </details>
      ) : null}
    </li>
  );
}

/** 转岗: 本人权限调整。选岗位模板 → 生成收回/新增/保留差异 → 勾选确认。 */
function TransferGrantSection({
  task,
  taskId,
  onChanged,
  canOperate,
}: {
  task: HandoverTaskDetailItem;
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
        <StatusBanner tone="signal" title={t("onboarding.templates.loadFailed")} message={(templatesQuery.error as Error).message} />
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        <div className="w-64">
          <Field label={t("handover.transfer.template")}>
            <SelectInput value={templateId} disabled={readOnly} onChange={(event) => setTemplateId(event.currentTarget.value)}>
              <option value="">{t("handover.transfer.templatePlaceholder")}</option>
              {templates.map((template) => (
                <option key={template.id} value={String(template.id)}>
                  {template.name}
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
          {confirmed ? (
            <div role="status">
              <StatusBanner tone="evergreen" title={t("handover.transfer.confirmedAt", { time: formatDateTime(plan.confirmed_at) })} />
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

function transferPlanVersion(plan: TransferPlanItem | null): string {
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
            const mappedName = nameMap.get(`${parsed.appKey}:${parsed.kind}:${parsed.key}`);
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
  task: HandoverTaskDetailItem;
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
