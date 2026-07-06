import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserSearchInput } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";
import type { MessageKey } from "../../../i18n/messages";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { HandoverAppActionRow, HandoverGrantItemRow, HandoverTaskDetailItem } from "../../../lib/domain";
import { cn } from "../../../lib/cn";
import { grantTypeLabel } from "../../../lib/status";
import {
  handoverActionStatusLabel,
  handoverActionStatusTone,
  previewAssets,
  previewHookSkipped,
} from "./lifecycleLabels";

const WIZARD_STEP_KEYS: MessageKey[] = [
  "handover.wizard.step.apps",
  "handover.wizard.step.receivers",
  "handover.wizard.step.grants",
  "handover.wizard.step.preview",
  "handover.wizard.step.execute",
];

const ACTIONABLE_STATUSES = new Set(["pending", "previewed", "failed"]);

interface ReceiverDraft {
  toUserId: string;
  release: boolean;
}

interface PreviewState {
  status: "loading" | "done" | "error";
  payload?: JsonObject;
  error?: string;
}

interface ExecuteState {
  status: "running" | "done" | "failed";
  error?: string;
}

interface HandoverWizardProps {
  task: HandoverTaskDetailItem;
  onClose: () => void;
}

/** 五步交接向导: 选应用 → 选接收人 → 选权限 → 预览数据 → 确认执行。所有进度都保存在服务端, 任何一步都可以关闭稍后继续。 */
export function HandoverWizard({ task, onClose }: HandoverWizardProps) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const detailQueryKey = ["console", "handover-task", String(task.id)];
  const grantItemsQueryKey = ["console", "handover-task", String(task.id), "grant-items"];
  const actionable = task.app_actions.filter((action) => ACTIONABLE_STATUSES.has(action.status));

  const [step, setStep] = useState(0);
  const [selected, setSelected] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(actionable.map((action) => [action.app_key, true])),
  );
  const [receivers, setReceivers] = useState<Record<string, ReceiverDraft>>(() =>
    Object.fromEntries(
      actionable.map((action) => [
        action.app_key,
        {
          toUserId: action.to_user?.user_id ?? "",
          release: action.policy?.unowned_strategy === "release_to_pool",
        },
      ]),
    ),
  );
  const [unifiedReceiver, setUnifiedReceiver] = useState("");
  const [perAppOpen, setPerAppOpen] = useState(false);
  const [grantSelection, setGrantSelection] = useState<Record<number, boolean>>({});
  const [previewState, setPreviewState] = useState<Record<string, PreviewState>>({});
  const [executeState, setExecuteState] = useState<Record<string, ExecuteState>>({});
  const [isExecuting, setIsExecuting] = useState(false);
  const previewStateRef = useRef(previewState);
  previewStateRef.current = previewState;

  const selectedApps = actionable.filter((action) => selected[action.app_key]);
  const selectedAppKeys = selectedApps.map((action) => action.app_key);

  const invalidateDetail = () => void queryClient.invalidateQueries({ queryKey: detailQueryKey });

  const grantItemsQuery = useQuery({
    queryKey: grantItemsQueryKey,
    queryFn: () =>
      apiRequest<ListPayload<HandoverGrantItemRow>>(`/console/api/v1/lifecycle/handover-tasks/${task.id}/grant-items`),
  });
  const grantItems = itemsFromPayload<HandoverGrantItemRow>(grantItemsQuery.data);

  // 勾选状态用服务端 selected 初始化; 只补新条目, 不覆盖本地已改动的勾选。
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grantItemsQuery.data]);

  const saveReceiversMutation = useMutation({
    mutationFn: (override?: Record<string, ReceiverDraft>) => {
      const effective = override ?? receivers;
      return apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}`, {
        method: "PATCH",
        body: {
          app_actions: selectedApps.map((action) => {
            const draft = effective[action.app_key] ?? { toUserId: "", release: false };
            return {
              app_key: action.app_key,
              to_user_id: draft.release ? null : draft.toUserId.trim() || null,
              release_to_pool: draft.release,
            };
          }),
        } satisfies JsonObject,
      });
    },
    onSuccess: () => {
      // 改接收人会使旧预览作废(服务端同样回退状态), 本地预览结果一并重置。
      setPreviewState({});
      invalidateDetail();
    },
  });

  const saveGrantsMutation = useMutation({
    mutationFn: () => {
      const items = grantItems
        .filter((item) => item.status === "pending" && selectedAppKeys.includes(item.app_key))
        .map((item) => ({ id: item.id, selected: grantSelection[item.id] ?? item.selected }));
      if (items.length === 0) {
        return Promise.resolve(null);
      }
      return apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}/grant-items`, {
        method: "PATCH",
        body: { items } satisfies JsonObject,
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: grantItemsQueryKey }),
  });

  const runPreview = async (appKey: string) => {
    setPreviewState((current) => ({ ...current, [appKey]: { status: "loading" } }));
    try {
      const payload = await apiRequest<{ app_action?: HandoverAppActionRow }>(
        `/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${appKey}/preview`,
        { method: "POST", body: {} },
      );
      setPreviewState((current) => ({
        ...current,
        [appKey]: { status: "done", payload: payload.app_action?.preview_payload ?? {} },
      }));
    } catch (error) {
      setPreviewState((current) => ({ ...current, [appKey]: { status: "error", error: (error as Error).message } }));
    }
  };

  // 进入预览步后为所选应用逐个生成预览; 已有结果的应用不重复请求。
  useEffect(() => {
    if (step !== 3) {
      return;
    }
    let cancelled = false;
    const run = async () => {
      for (const appKey of selectedAppKeys) {
        if (cancelled || previewStateRef.current[appKey]) {
          continue;
        }
        await runPreview(appKey);
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

  const runExecute = async () => {
    setIsExecuting(true);
    for (const appKey of selectedAppKeys) {
      if (executeState[appKey]?.status === "done") {
        continue;
      }
      setExecuteState((current) => ({ ...current, [appKey]: { status: "running" } }));
      try {
        await apiRequest(`/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${appKey}/execute`, {
          method: "POST",
          body: {},
        });
        setExecuteState((current) => ({ ...current, [appKey]: { status: "done" } }));
      } catch (error) {
        setExecuteState((current) => ({ ...current, [appKey]: { status: "failed", error: (error as Error).message } }));
      }
      invalidateDetail();
    }
    setIsExecuting(false);
  };

  const executeStatuses = selectedAppKeys.map((appKey) => executeState[appKey]?.status);
  const allExecuted = executeStatuses.length > 0 && executeStatuses.every((status) => status === "done");
  const someExecuteFailed = executeStatuses.some((status) => status === "failed");

  const goNext = () => {
    if (step === 1) {
      // 防漏: 已在「统一接收人」选了人但忘点「应用到所选应用」时, 下一步自动
      // 把该接收人补到所有还没指定接收人/释放策略的应用上。
      const unified = unifiedReceiver.trim();
      let effective = receivers;
      if (unified) {
        const merged = { ...receivers };
        let changed = false;
        for (const appKey of selectedAppKeys) {
          const draft = merged[appKey];
          if (!draft?.release && !draft?.toUserId?.trim()) {
            merged[appKey] = { toUserId: unified, release: false };
            changed = true;
          }
        }
        if (changed) {
          effective = merged;
          setReceivers(merged);
        }
      }
      saveReceiversMutation.mutate(effective, { onSuccess: () => setStep(2) });
      return;
    }
    if (step === 2) {
      saveGrantsMutation.mutate(undefined, { onSuccess: () => setStep(3) });
      return;
    }
    setStep((current) => Math.min(current + 1, WIZARD_STEP_KEYS.length - 1));
  };

  const saveAndClose = () => {
    if (step === 1) {
      saveReceiversMutation.mutate(undefined, { onSuccess: onClose });
      return;
    }
    if (step === 2) {
      saveGrantsMutation.mutate(undefined, { onSuccess: onClose });
      return;
    }
    onClose();
  };

  const isSaving = saveReceiversMutation.isPending || saveGrantsMutation.isPending;
  const nextDisabled = (step === 0 && selectedApps.length === 0) || isSaving || isExecuting;

  return (
    <Dialog title={t("handover.wizard.title")} size="xl" onClose={onClose}>
      <div className="space-y-5">
        <WizardStepIndicator step={step} />
        {step === 0 ? (
          <StepSection hint={t("handover.wizard.apps.hint")}>
            {actionable.length === 0 ? (
              <p className="text-body leading-5 text-ink-soft">{t("handover.wizard.apps.empty")}</p>
            ) : (
              <>
                <ul className="grid gap-2">
                  {actionable.map((action) => (
                    <li key={action.app_key}>
                      <label className="flex items-center gap-2.5 rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5 text-body text-ink">
                        <input
                          type="checkbox"
                          checked={Boolean(selected[action.app_key])}
                          onChange={(event) =>
                            setSelected((current) => ({ ...current, [action.app_key]: event.currentTarget.checked }))
                          }
                        />
                        <span className="flex-1 font-medium">{action.app_name || action.app_key}</span>
                        <Badge tone={handoverActionStatusTone(action.status)}>
                          {handoverActionStatusLabel(t, action.status)}
                        </Badge>
                      </label>
                    </li>
                  ))}
                </ul>
                <p className="text-caption text-ink-faint">
                  {t("handover.wizard.apps.selectedCount", { count: selectedApps.length })}
                </p>
              </>
            )}
          </StepSection>
        ) : null}
        {step === 1 ? (
          <StepSection hint={t("handover.wizard.receivers.hint")}>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-64 flex-1">
                <Field label={t("handover.wizard.receivers.unified")} as="group">
                  <UserSearchInput
                    value={unifiedReceiver}
                    aria-label={t("handover.wizard.receivers.unified")}
                    onChange={setUnifiedReceiver}
                  />
                </Field>
              </div>
              <Button
                type="button"
                disabled={!unifiedReceiver.trim()}
                onClick={() =>
                  setReceivers((current) => {
                    const next = { ...current };
                    for (const appKey of selectedAppKeys) {
                      next[appKey] = { toUserId: unifiedReceiver.trim(), release: false };
                    }
                    return next;
                  })
                }
              >
                {t("handover.wizard.receivers.applyAll")}
              </Button>
            </div>
            <Button type="button" variant="ghost" onClick={() => setPerAppOpen((open) => !open)}>
              {t("handover.wizard.receivers.perApp")}
            </Button>
            {perAppOpen ? (
              <ul className="grid gap-2.5">
                {selectedApps.map((action) => {
                  const draft = receivers[action.app_key] ?? { toUserId: "", release: false };
                  const appName = action.app_name || action.app_key;
                  return (
                    <li
                      key={action.app_key}
                      className="flex flex-wrap items-center gap-3 rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5"
                    >
                      <span className="min-w-32 text-body font-medium text-ink">{appName}</span>
                      <div className="min-w-56 flex-1">
                        <UserSearchInput
                          value={draft.release ? "" : draft.toUserId}
                          aria-label={`${appName} ${t("handover.wizard.receivers.receiver")}`}
                          onChange={(value) =>
                            setReceivers((current) => ({
                              ...current,
                              [action.app_key]: { toUserId: value, release: false },
                            }))
                          }
                        />
                      </div>
                      <label className="inline-flex items-center gap-1.5 text-body text-ink-soft">
                        <input
                          type="checkbox"
                          checked={draft.release}
                          onChange={(event) =>
                            setReceivers((current) => ({
                              ...current,
                              [action.app_key]: {
                                toUserId: event.currentTarget.checked ? "" : draft.toUserId,
                                release: event.currentTarget.checked,
                              },
                            }))
                          }
                        />
                        <span>{t("handover.wizard.receivers.releaseToPool")}</span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            ) : null}
            {saveReceiversMutation.error ? (
              <StatusBanner
                tone="signal"
                title={t("handover.wizard.receivers.saveFailed")}
                message={(saveReceiversMutation.error as Error).message}
              />
            ) : null}
          </StepSection>
        ) : null}
        {step === 2 ? (
          <StepSection hint={t("handover.wizard.grants.hint")}>
            {grantItemsQuery.error ? (
              <StatusBanner
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
            {saveGrantsMutation.error ? (
              <StatusBanner
                tone="signal"
                title={t("handover.wizard.grants.saveFailed")}
                message={(saveGrantsMutation.error as Error).message}
              />
            ) : null}
          </StepSection>
        ) : null}
        {step === 3 ? (
          <StepSection hint={t("handover.wizard.preview.hint")}>
            <ul className="grid gap-2.5">
              {selectedApps.map((action) => (
                <li key={action.app_key} className="rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <strong className="text-body text-ink">{action.app_name || action.app_key}</strong>
                    {previewState[action.app_key]?.status === "error" ? (
                      <Button size="sm" type="button" onClick={() => void runPreview(action.app_key)}>
                        {t("handover.wizard.preview.retry")}
                      </Button>
                    ) : null}
                  </div>
                  <PreviewResultLine
                    action={action}
                    state={previewState[action.app_key]}
                    receiver={receivers[action.app_key]}
                  />
                </li>
              ))}
            </ul>
          </StepSection>
        ) : null}
        {step === 4 ? (
          <StepSection hint={t("handover.wizard.execute.hint")}>
            <ul className="grid gap-2.5">
              {selectedApps.map((action) => (
                <ExecuteSummaryRow
                  key={action.app_key}
                  action={action}
                  receiver={receivers[action.app_key]}
                  grantCount={
                    grantItems.filter(
                      (item) => item.app_key === action.app_key && (grantSelection[item.id] ?? item.selected),
                    ).length
                  }
                  assetCount={previewAssets(previewState[action.app_key]?.payload).reduce(
                    (total, asset) => total + asset.count,
                    0,
                  )}
                  state={executeState[action.app_key]}
                  disabled={isExecuting}
                  onRetry={() => {
                    setExecuteState((current) => {
                      const next = { ...current };
                      delete next[action.app_key];
                      return next;
                    });
                    void (async () => {
                      setIsExecuting(true);
                      setExecuteState((current) => ({ ...current, [action.app_key]: { status: "running" } }));
                      try {
                        await apiRequest(
                          `/console/api/v1/lifecycle/handover-tasks/${task.id}/actions/${action.app_key}/retry`,
                          { method: "POST", body: {} },
                        );
                        setExecuteState((current) => ({ ...current, [action.app_key]: { status: "done" } }));
                      } catch (error) {
                        setExecuteState((current) => ({
                          ...current,
                          [action.app_key]: { status: "failed", error: (error as Error).message },
                        }));
                      }
                      setIsExecuting(false);
                      invalidateDetail();
                    })();
                  }}
                />
              ))}
            </ul>
            {allExecuted ? (
              <div role="status">
                <StatusBanner tone="evergreen" title={t("handover.wizard.execute.done")} />
              </div>
            ) : null}
            {someExecuteFailed && !isExecuting ? (
              <StatusBanner tone="amber" title={t("handover.wizard.execute.failedSome")} />
            ) : null}
          </StepSection>
        ) : null}
        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-ink/10 pt-4">
          <Button type="button" variant="ghost" disabled={isSaving || isExecuting} onClick={saveAndClose}>
            {t("handover.wizard.saveLater")}
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            {step > 0 ? (
              <Button type="button" disabled={isSaving || isExecuting} onClick={() => setStep(step - 1)}>
                {t("common.back")}
              </Button>
            ) : null}
            {step < 4 ? (
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
                disabled={isExecuting || selectedApps.length === 0}
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

function WizardStepIndicator({ step }: { step: number }) {
  const { t } = useI18n();
  return (
    <ol className="flex flex-wrap gap-x-1 gap-y-2 border-b border-ink/12 pb-4" aria-label={t("handover.wizard.stepsAria")}>
      {WIZARD_STEP_KEYS.map((labelKey, index) => {
        const isActive = index === step;
        const isDone = index < step;
        return (
          <li key={labelKey} className="flex items-center gap-1" aria-current={isActive ? "step" : undefined}>
            {index > 0 ? <span aria-hidden="true" className="mx-1 hidden h-px w-5 bg-ink/15 sm:block" /> : null}
            <span
              className={cn(
                "flex items-center gap-2 rounded-[3px] px-2 py-1 text-sm font-semibold",
                isActive ? "text-ink" : "text-ink-soft",
              )}
            >
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
              {t(labelKey)}
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
  apps: HandoverAppActionRow[];
  items: HandoverGrantItemRow[];
  selection: Record<number, boolean>;
  onToggle: (id: number, checked: boolean) => void;
}) {
  const { t } = useI18n();
  const grouped = apps
    .map((action) => ({ action, items: items.filter((item) => item.app_key === action.app_key) }))
    .filter((group) => group.items.length > 0);

  if (grouped.length === 0) {
    return <p className="text-body leading-5 text-ink-soft">{t("handover.wizard.grants.empty")}</p>;
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
                  <span className="flex-1">
                    <span className="font-medium">{item.name || item.key}</span>
                    {item.scope_key ? <span className="ml-2 text-caption text-ink-faint">{item.scope_key}</span> : null}
                  </span>
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

function PreviewResultLine({
  action,
  state,
  receiver,
}: {
  action: HandoverAppActionRow;
  state: PreviewState | undefined;
  receiver: ReceiverDraft | undefined;
}) {
  const { t } = useI18n();
  if (!state || state.status === "loading") {
    return <p className="mt-1 text-body text-ink-faint">{t("handover.wizard.preview.loading")}</p>;
  }
  if (state.status === "error") {
    return (
      <p className="mt-1 text-body leading-5 text-signal">
        {t("handover.wizard.preview.failed")}
        {state.error ? ` - ${state.error}` : ""}
      </p>
    );
  }
  if (previewHookSkipped(state.payload)) {
    return <p className="mt-1 text-body leading-5 text-ink-soft">{t("handover.wizard.preview.noHook")}</p>;
  }
  const assets = previewAssets(state.payload);
  if (assets.length === 0) {
    return <p className="mt-1 text-body leading-5 text-ink-soft">{t("handover.wizard.preview.empty")}</p>;
  }
  const itemsText = assets
    .map((asset) => t("handover.wizard.preview.asset", { count: asset.count, label: asset.label || asset.type }))
    .join("、");
  const receiverName = action.to_user?.name || receiver?.toUserId || "";
  const line = receiver?.release
    ? t("handover.wizard.preview.releaseToPool", { items: itemsText })
    : t("handover.wizard.preview.transferTo", { items: itemsText, name: receiverName });
  return <p className="mt-1 text-body leading-5 text-ink-soft">{line}</p>;
}

function ExecuteSummaryRow({
  action,
  receiver,
  grantCount,
  assetCount,
  state,
  disabled,
  onRetry,
}: {
  action: HandoverAppActionRow;
  receiver: ReceiverDraft | undefined;
  grantCount: number;
  assetCount: number;
  state: ExecuteState | undefined;
  disabled: boolean;
  onRetry: () => void;
}) {
  const { t } = useI18n();
  const receiverLabel = receiver?.release
    ? t("handover.wizard.receivers.releaseToPool")
    : action.to_user?.name || receiver?.toUserId || t("handover.card.waiting");
  return (
    <li className="rounded-[3px] border border-ink/12 bg-paper-soft px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong className="text-body text-ink">{action.app_name || action.app_key}</strong>
        {state?.status === "running" ? (
          <Badge tone="amber">{t("handover.actionStatus.executing")}</Badge>
        ) : state?.status === "done" ? (
          <Badge tone="evergreen">{t("handover.actionStatus.done")}</Badge>
        ) : state?.status === "failed" ? (
          <span className="inline-flex items-center gap-1.5">
            <Badge tone="signal">{t("handover.actionStatus.failed")}</Badge>
            <Button size="sm" type="button" disabled={disabled} onClick={onRetry}>
              {t("handover.card.retry")}
            </Button>
          </span>
        ) : null}
      </div>
      <p className="mt-1 text-caption leading-5 text-ink-soft">
        {t("handover.wizard.receivers.receiver")}: {receiverLabel}
        {" · "}
        {t("handover.wizard.execute.grantsCount", { count: grantCount })}
        {" · "}
        {t("handover.wizard.execute.assetsCount", { count: assetCount })}
      </p>
      {state?.status === "failed" && state.error ? (
        <p className="mt-1 text-caption leading-5 text-signal">{state.error}</p>
      ) : null}
    </li>
  );
}
