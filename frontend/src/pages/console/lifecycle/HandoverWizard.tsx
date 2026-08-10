import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { StatusBanner } from "../../../components/StatusBanner";
import { AssetAllocator } from "../../../features/handover/AssetAllocator";
import { HandoverUserPicker } from "../../../features/handover/HandoverUserPicker";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { HandoverAction, HandoverActionPayload, HandoverGrantItemRow, HandoverTaskDetail } from "../../../lib/domain";
import { cn } from "../../../lib/cn";
import { grantTypeLabel } from "../../../lib/status";
import {
  canSelectActionForWizard,
  HANDOVER_WIZARD_STEPS,
  useHandoverWizardController,
  type HandoverWizardStepId,
  stepIndex,
} from "./handoverWizardController";
import { handoverActionStatusLabel, handoverActionStatusTone } from "./lifecycleLabels";

const ACTIONABLE_STATUSES = new Set(["pending", "previewed", "failed"]);

interface HandoverWizardProps {
  task: HandoverTaskDetail;
  onClose: () => void;
}

/** 四段交接向导: 应用 → 授权 → 预演与分配 → 执行。接收人下沉到资产条目级。 */
export function HandoverWizard({ task, onClose }: HandoverWizardProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const detailQueryKey = useMemo(() => ["console", "handover-task", String(task.id)], [task.id]);
  const grantItemsQueryKey = useMemo(
    () => ["console", "handover-task", String(task.id), "grant-items"],
    [task.id],
  );

  const [batchActions] = useState(() =>
    task.actions.filter((action) => ACTIONABLE_STATUSES.has(action.status) || action.status === "blocked"),
  );
  const [selected, setSelected] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      batchActions.map((action) => [action.app_key, canSelectActionForWizard(action) && ACTIONABLE_STATUSES.has(action.status)]),
    ),
  );
  const [localActions, setLocalActions] = useState<Record<string, HandoverAction>>(() =>
    Object.fromEntries(task.actions.map((action) => [action.app_key, action])),
  );
  const [grantSelection, setGrantSelection] = useState<Record<number, boolean>>({});
  const [previewed, setPreviewed] = useState<Record<string, boolean>>({});
  const [executeState, setExecuteState] = useState<Record<string, "running" | "done" | "failed" | "async_pending">>({});
  const [isExecuting, setIsExecuting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wizard = useHandoverWizardController();
  const step = wizard.step;

  const selectedApps = useMemo(
    () => batchActions.filter((action) => selected[action.app_key] && canSelectActionForWizard(action)),
    [batchActions, selected],
  );
  const blockedCount = batchActions.filter((action) => action.status === "blocked").length;

  const invalidateDetail = useCallback(
    () => void queryClient.invalidateQueries({ queryKey: detailQueryKey }),
    [detailQueryKey, queryClient],
  );

  const grantItemsQuery = useQuery({
    queryKey: grantItemsQueryKey,
    queryFn: () =>
      apiRequest<ListPayload<HandoverGrantItemRow>>(`/console/api/v1/lifecycle/handover-tasks/${task.id}/grant-items`),
    enabled: task.kind === "offboard",
  });
  const grantItems = useMemo(
    () => itemsFromPayload<HandoverGrantItemRow>(grantItemsQuery.data),
    [grantItemsQuery.data],
  );

  useEffect(() => {
    setGrantSelection((current) => {
      const next = { ...current };
      for (const item of grantItems) {
        if (!(item.id in next)) {
          next[item.id] = item.selected;
        }
      }
      return next;
    });
  }, [grantItems]);

  const saveGrantsMutation = useMutation({
    mutationFn: async () => {
      const items = grantItems
        .filter((item) => item.status === "pending" && selectedApps.some((a) => a.app_key === item.app_key))
        .map((item) => ({ ...item, nextSelected: grantSelection[item.id] ?? item.selected }))
        .filter((item) => item.selected !== item.nextSelected);
      if (items.length === 0) {
        return;
      }
      await apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}/grant-items`, {
        method: "PATCH",
        body: { items: items.map((item) => ({ id: item.id, selected: item.nextSelected })) } satisfies JsonObject,
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: grantItemsQueryKey }),
  });

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

  const allPreviewed =
    selectedApps.length > 0 &&
    selectedApps.every(
      (action) => previewed[action.app_key] || localActions[action.app_key]?.status === "previewed",
    );

  const goNext = () => {
    if (step === "apps") {
      if (selectedApps.length === 0) {
        return;
      }
      if (task.kind === "offboard") {
        wizard.goTo("grants");
      } else {
        wizard.goTo("allocate");
      }
      return;
    }
    if (step === "grants") {
      saveGrantsMutation.mutate(undefined, { onSuccess: () => wizard.goTo("allocate") });
      return;
    }
    if (step === "allocate" && !allPreviewed) {
      return;
    }
    wizard.goNext();
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
        setExecuteState((s) => ({
          ...s,
          [action.app_key]:
            payload.action.status === "done"
              ? "done"
              : payload.action.status === "async_pending"
                ? "async_pending"
                : "failed",
        }));
      } catch (err) {
        setExecuteState((s) => ({ ...s, [action.app_key]: "failed" }));
        setError((err as Error).message);
      }
      invalidateDetail();
    }
    setIsExecuting(false);
  };

  const allExecuted =
    selectedApps.length > 0 && selectedApps.every((a) => executeState[a.app_key] === "done");
  const isSaving = saveGrantsMutation.isPending;
  const nextDisabled =
    (step === "apps" && selectedApps.length === 0) ||
    (step === "grants" && (grantItemsQuery.isLoading || Boolean(grantItemsQuery.error))) ||
    (step === "allocate" && !allPreviewed) ||
    isSaving ||
    isExecuting;

  return (
    <Dialog title={t("handover.wizard.title")} size="xl" onClose={() => !isExecuting && onClose()} closeDisabled={isExecuting}>
      <div className="space-y-5">
        <WizardStepIndicator step={step} />
        {error ? <StatusBanner live="alert" tone="signal" title={error} /> : null}

        {step === "apps" ? (
          <StepSection hint={t("handover.wizard.apps.hint")}>
            {batchActions.length === 0 ? (
              <p className="text-body text-ink-soft">{t("handover.wizard.apps.empty")}</p>
            ) : (
              <ul className="grid gap-2">
                {batchActions.map((action) => {
                  const blocked = !canSelectActionForWizard(action);
                  return (
                    <li key={action.app_key}>
                      <label
                        className={cn(
                          "flex items-center gap-2.5 rounded-[3px] border px-3 py-2.5 text-body",
                          blocked ? "border-signal/40 bg-signal/5 text-signal" : "border-ink/12 bg-paper-soft text-ink",
                        )}
                      >
                        <input
                          type="checkbox"
                          disabled={blocked}
                          checked={Boolean(selected[action.app_key]) && !blocked}
                          onChange={(event) =>
                            setSelected((current) => ({ ...current, [action.app_key]: event.currentTarget.checked }))
                          }
                        />
                        <span className="flex-1 font-medium">{action.app_name || action.app_key}</span>
                        {blocked ? (
                          <span className="text-caption">{t("handover.wizard.apps.blocked")}</span>
                        ) : (
                          <Badge tone={handoverActionStatusTone(action.status)}>
                            {handoverActionStatusLabel(t, action.status)}
                          </Badge>
                        )}
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="text-caption text-ink-faint">
              {t("handover.wizard.apps.selectedCount", { count: selectedApps.length })}
            </p>
          </StepSection>
        ) : null}

        {step === "grants" ? (
          <StepSection hint={t("handover.wizard.grants.hint")}>
            {grantItemsQuery.error ? (
              <StatusBanner
                live="alert"
                tone="signal"
                title={t("handover.wizard.grants.loadFailed")}
                message={(grantItemsQuery.error as Error).message}
              />
            ) : null}
            {grantItemsQuery.isLoading ? <p className="text-body text-ink-faint">{t("common.loading")}</p> : null}
            {!grantItemsQuery.isLoading && !grantItemsQuery.error ? (
              <GrantItemsChecklist
                apps={selectedApps}
                items={grantItems}
                selection={grantSelection}
                onToggle={(id, checked) => setGrantSelection((current) => ({ ...current, [id]: checked }))}
              />
            ) : null}
          </StepSection>
        ) : null}

        {step === "allocate" ? (
          <StepSection hint={t("handover.wizard.allocate.hint")}>
            <ul className="grid gap-4">
              {selectedApps.map((base) => {
                const action = localActions[base.app_key] ?? base;
                return (
                  <li key={action.app_key} className="space-y-2 rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-3">
                    <div className="flex items-center justify-between gap-2">
                      <strong className="text-body text-ink">{action.app_name || action.app_key}</strong>
                      {action.status !== "previewed" ? (
                        <Button size="sm" type="button" onClick={() => void runPreview(action.app_key)}>
                          {t("handover.portal.detail.preview")}
                        </Button>
                      ) : (
                        <Button size="sm" type="button" onClick={() => void runPreview(action.app_key)}>
                          {t("handover.portal.detail.repreview")}
                        </Button>
                      )}
                    </div>
                    {task.kind === "offboard" && action.status === "previewed" ? (
                      <div>
                        <p className="mb-1 text-caption text-ink-faint">{t("handover.wizard.grantReceiver")}</p>
                        <HandoverUserPicker
                          surface="console"
                          taskId={task.id}
                          value={action.grant_receiver}
                          onChange={async (user) => {
                            const payload = await apiRequest<HandoverActionPayload>(
                              `/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${action.app_key}`,
                              { method: "PATCH", body: { grant_receiver_user_id: user?.user_id ?? null } },
                            );
                            setLocalActions((s) => ({ ...s, [action.app_key]: payload.action }));
                            setPreviewed((s) => ({ ...s, [action.app_key]: false }));
                          }}
                        />
                        <p className="mt-1 text-caption text-ink-faint">{t("handover.wizard.grantReceiverHint")}</p>
                      </div>
                    ) : null}
                    {action.status === "previewed" ? (
                      <AssetAllocator
                        surface="console"
                        taskId={task.id}
                        action={action}
                        onActionUpdated={(patch) => {
                          setLocalActions((s) => ({
                            ...s,
                            [action.app_key]: {
                              ...action,
                              asset_types: patch.asset_types ?? action.asset_types,
                              confirm_version: patch.confirm_version ?? action.confirm_version,
                              overrides_version: patch.overrides_version ?? action.overrides_version,
                            },
                          }));
                        }}
                      />
                    ) : (
                      <p className="text-body text-ink-faint">{t("handover.wizard.preview.loading")}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          </StepSection>
        ) : null}

        {step === "execute" ? (
          <StepSection hint={t("handover.wizard.execute.hint")}>
            {blockedCount > 0 ? (
              <StatusBanner
                live="status"
                tone="amber"
                title={t("handover.wizard.execute.blockedSummary", { count: blockedCount })}
              />
            ) : null}
            <ul className="grid gap-2">
              {selectedApps.map((base) => {
                const action = localActions[base.app_key] ?? base;
                const state = executeState[action.app_key];
                return (
                  <li key={action.app_key} className="rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <strong className="text-body">{action.app_name || action.app_key}</strong>
                      {state === "done" ? (
                        <Badge tone="evergreen">{t("handover.actionStatus.done")}</Badge>
                      ) : state === "failed" ? (
                        <Badge tone="signal">{t("handover.actionStatus.failed")}</Badge>
                      ) : state === "running" ? (
                        <Badge tone="amber">{t("handover.actionStatus.executing")}</Badge>
                      ) : state === "async_pending" ? (
                        <Badge tone="amber">{t("handover.actionStatus.asyncPending")}</Badge>
                      ) : (
                        <Badge tone={handoverActionStatusTone(action.status)}>
                          {handoverActionStatusLabel(t, action.status)}
                        </Badge>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            {allExecuted ? <StatusBanner live="status" tone="evergreen" title={t("handover.wizard.execute.done")} /> : null}
          </StepSection>
        ) : null}

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-ink/10 pt-4">
          <Button type="button" variant="ghost" disabled={isSaving || isExecuting} onClick={onClose}>
            {t("handover.wizard.saveLater")}
          </Button>
          <div className="flex flex-wrap gap-2">
            {!wizard.isFirstStep ? (
              <Button type="button" disabled={isSaving || isExecuting} onClick={wizard.goBack}>
                {t("common.back")}
              </Button>
            ) : null}
            {!wizard.isLastStep ? (
              <Button type="button" variant="primary" loading={isSaving} disabled={nextDisabled} onClick={goNext}>
                {t("common.next")}
              </Button>
            ) : allExecuted ? (
              <Button type="button" variant="primary" onClick={onClose}>
                {t("common.done")}
              </Button>
            ) : (
              <Button
                type="button"
                variant="primary"
                loading={isExecuting}
                disabled={isExecuting || selectedApps.length === 0 || !allPreviewed}
                onClick={() => void runExecute()}
              >
                {t("handover.wizard.execute.run")}
              </Button>
            )}
          </div>
        </footer>
      </div>
    </Dialog>
  );
}

function WizardStepIndicator({ step }: { step: HandoverWizardStepId }) {
  const { t } = useI18n();
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 border-b border-ink/12 pb-4" aria-label={t("handover.wizard.stepsAria")}>
      {HANDOVER_WIZARD_STEPS.map((item, index) => {
        const activeIndex = stepIndex(step);
        const isActive = item.id === step;
        const isDone = index < activeIndex;
        return (
          <li key={item.id} className="flex items-center gap-1" aria-current={isActive ? "step" : undefined}>
            {index > 0 ? <span aria-hidden="true" className="mx-1 hidden h-px w-5 bg-ink/15 sm:block" /> : null}
            <span className={cn("flex items-center gap-2 rounded-[3px] px-2 py-1 text-sm font-semibold", isActive ? "text-ink" : "text-ink-soft")}>
              <span
                aria-hidden="true"
                className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  isActive && "border-accent bg-accent text-paper",
                  isDone && "border-evergreen bg-evergreen/10 text-evergreen",
                  !isActive && !isDone && "border-ink/20 text-ink-soft",
                )}
              >
                {isDone ? <Check size={13} /> : index + 1}
              </span>
              {t(item.labelKey)}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function StepSection({ hint, children }: { hint: string; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <p className="text-body leading-5 text-ink-soft">{hint}</p>
      {children}
    </section>
  );
}

function GrantItemsChecklist({
  apps,
  items,
  selection,
  onToggle,
}: {
  apps: HandoverAction[];
  items: HandoverGrantItemRow[];
  selection: Record<number, boolean>;
  onToggle: (id: number, checked: boolean) => void;
}) {
  const { t } = useI18n();
  const grouped = apps
    .map((action) => ({ action, items: items.filter((item) => item.app_key === action.app_key) }))
    .filter((group) => group.items.length > 0);
  if (grouped.length === 0) {
    return <p className="text-body text-ink-soft">{t("handover.wizard.grants.empty")}</p>;
  }
  return (
    <div className="space-y-4">
      {grouped.map(({ action, items: appItems }) => (
        <div key={action.app_key} className="space-y-2">
          <h3 className="text-body font-semibold text-ink">{action.app_name || action.app_key}</h3>
          <ul className="grid gap-1.5">
            {appItems.map((item) => (
              <li key={item.id}>
                <label className="flex items-center gap-2.5 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2 text-body text-ink">
                  <input
                    type="checkbox"
                    disabled={item.status !== "pending"}
                    checked={selection[item.id] ?? item.selected}
                    onChange={(event) => onToggle(item.id, event.currentTarget.checked)}
                  />
                  <span className="flex-1 font-medium">{item.name || item.key}</span>
                  <span className="text-caption text-ink-faint">
                    {item.kind === "group" ? t("handover.diff.kind.group") : t("handover.diff.kind.permission")}
                    {" · "}
                    {grantTypeLabel(t, item.grant_type)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
