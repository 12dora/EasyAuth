import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, SelectInput, TextArea } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import { cn } from "../../lib/cn";
import type { HandoverAction, HandoverActionPayload, HandoverTaskDetail } from "../../lib/domain";
import { AssetAllocator, buildExecuteConfirmParts } from "./AssetAllocator";
import { HandoverUserPicker } from "./HandoverUserPicker";
import { handoverActionPath, type HandoverSurface } from "./surface";

export interface HandoverActionPanelProps {
  surface: HandoverSurface;
  task: HandoverTaskDetail;
  action: HandoverAction;
  /** 控制台超管专属能力 */
  isConsoleSuperuser?: boolean;
  isLocalAdmin?: boolean;
  onTaskRefresh: () => void;
  onActionReplace: (action: HandoverAction) => void;
}

export function HandoverActionPanel({
  surface,
  task,
  action,
  isConsoleSuperuser = false,
  onTaskRefresh,
  onActionReplace,
}: HandoverActionPanelProps) {
  const { t, formatDateTime: fmt } = useI18n();
  const queryClient = useQueryClient();
  const [allocatorBusy, setAllocatorBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [skipOpen, setSkipOpen] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);
  const [asyncAbandonOpen, setAsyncAbandonOpen] = useState(false);
  const [asyncOutcome, setAsyncOutcome] = useState<"done" | "failed">("done");
  const [asyncReason, setAsyncReason] = useState("");

  const status = action.status;
  // batch_progress 非 null 期间禁止改分配（02 §4 / 01 batch_plan_in_progress）
  const readOnly =
    status === "executing" || status === "async_pending" || action.batch_progress != null;
  const poll = status === "executing" || status === "async_pending";

  const handleSnapshotStale = () => {
    setConfirmOpen(false);
    setBanner(t("handover.portal.detail.snapshotStale"));
    onTaskRefresh();
  };

  const previewMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(handoverActionPath(surface, task.id, action.app_key, "preview"), {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      setBanner(null);
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => {
      handleActionError(error, setBanner, t, onTaskRefresh, setConfirmOpen);
    },
  });

  const executeMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(handoverActionPath(surface, task.id, action.app_key, "execute"), {
        method: "POST",
        body: { confirm_version: action.confirm_version },
      }),
    onSuccess: (payload) => {
      setConfirmOpen(false);
      setBanner(null);
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => {
      handleActionError(error, setBanner, t, onTaskRefresh, setConfirmOpen);
    },
  });

  const retryMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(handoverActionPath(surface, task.id, action.app_key, "retry"), {
        method: "POST",
        body: {},
      }),
    onSuccess: (payload) => {
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const skipMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(handoverActionPath(surface, task.id, action.app_key, "skip"), {
        method: "POST",
        body: { reason: skipReason.trim() },
      }),
    onSuccess: (payload) => {
      setSkipOpen(false);
      setSkipReason("");
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const grantReceiverMutation = useMutation({
    mutationFn: (userId: string | null) =>
      apiRequest<HandoverActionPayload>(handoverActionPath(surface, task.id, action.app_key), {
        method: "PATCH",
        body: { grant_receiver_user_id: userId },
      }),
    onSuccess: (payload) => {
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const asyncAbandonMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverActionPayload>(
        handoverActionPath(surface, task.id, action.app_key, "async-abandon"),
        {
          method: "POST",
          body: {
            outcome: asyncOutcome,
            reason: asyncReason.trim(),
            summary: null,
          },
        },
      ),
    onSuccess: (payload) => {
      setAsyncAbandonOpen(false);
      setAsyncReason("");
      onActionReplace(payload.action);
      onTaskRefresh();
    },
    onError: (error: Error) => setBanner(error.message),
  });

  const toneClass =
    status === "blocked" || (status === "failed" && !action.data_completed_at)
      ? "border-signal/30 bg-signal/5"
      : status === "failed" && action.data_completed_at
        ? "border-amber/30 bg-amber/5"
        : status === "async_attention_required"
          ? "border-amber/30 bg-amber/5"
          : status === "skipped"
            ? "border-ink/10 bg-paper-deep/50"
            : status === "done"
              ? "border-evergreen/30 bg-evergreen/5"
              : "border-ink/12 bg-paper-soft";

  const skipDisplay = resolveSkipDisplay(action, t, fmt);

  const confirmParts = buildExecuteConfirmParts(action);
  const primaryReceiver = resolveConfirmReceiver(confirmParts, action, t);

  return (
    <li className={cn("space-y-3 rounded-[3px] border px-4 py-3", toneClass)} data-testid={`action-panel-${action.app_key}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong className="text-body text-ink">{action.app_name || action.app_key}</strong>
        <Badge tone={actionStatusBadgeTone(status)}>{actionStatusLabel(t, status)}</Badge>
      </div>

      {banner ? <StatusBanner live="alert" tone="signal" title={banner} /> : null}

      {action.approval_instance_warning ? (
        <StatusBanner
          live="status"
          tone="amber"
          title={action.approval_instance_warning.message}
          message={action.approval_instance_warning.link}
        />
      ) : null}

      {status === "blocked" ? (
        <>
          <p className="text-body text-ink-soft">{t("handover.portal.detail.blockedBody")}</p>
          {isConsoleSuperuser && surface === "console" ? (
            <Button type="button" variant="ghost-danger" size="sm" onClick={() => setSkipOpen(true)}>
              {t("handover.console.skip")}
            </Button>
          ) : null}
        </>
      ) : null}

      {status === "skipped" ? (
        <p className="text-body text-ink-soft">{skipDisplay}</p>
      ) : null}

      {status === "async_attention_required" ? (
        <div className="space-y-2">
          <p className="text-body text-ink-soft">{t("handover.portal.detail.asyncAttention")}</p>
          {isConsoleSuperuser && surface === "console" ? (
            <Button type="button" size="sm" variant="ghost-danger" onClick={() => setAsyncAbandonOpen(true)}>
              {t("handover.console.asyncAbandon")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {status === "pending" ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-body text-ink-soft">{t("handover.portal.detail.notPreviewed")}</span>
          {action.allowed_actions.includes("preview") ? (
            <Button type="button" size="sm" loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
              {t("handover.portal.detail.preview")}
            </Button>
          ) : null}
        </div>
      ) : null}

      {status === "previewed" ? (
        <div className="space-y-3">
          {task.kind === "offboard" ? (
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-56">
                <p className="mb-1 text-caption text-ink-faint">{t("handover.wizard.grantReceiver")}</p>
                <HandoverUserPicker
                  surface={surface}
                  taskId={task.id}
                  value={action.grant_receiver}
                  disabled={readOnly || grantReceiverMutation.isPending}
                  onChange={(user) => grantReceiverMutation.mutate(user?.user_id ?? null)}
                />
              </div>
              <p className="text-caption text-ink-faint">{t("handover.wizard.grantReceiverHint")}</p>
            </div>
          ) : null}
          <AssetAllocator
            surface={surface}
            taskId={task.id}
            action={action}
            readOnly={readOnly}
            onBusyChange={setAllocatorBusy}
            onSnapshotStale={handleSnapshotStale}
            onActionUpdated={(patch) => {
              onActionReplace({
                ...action,
                asset_types: patch.asset_types ?? action.asset_types,
                confirm_version: patch.confirm_version ?? action.confirm_version,
                overrides_version: patch.overrides_version ?? action.overrides_version,
              });
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            {action.allowed_actions.includes("preview") ? (
              <Button type="button" size="sm" loading={previewMutation.isPending} onClick={() => previewMutation.mutate()}>
                {t("handover.portal.detail.repreview")}
              </Button>
            ) : null}
            {action.batch_progress ? (
              <>
                <span className="text-caption text-ink-soft">
                  {t("handover.portal.detail.batchProgress", {
                    completed: action.batch_progress.completed,
                    total: action.batch_progress.total,
                  })}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  disabled={allocatorBusy}
                  onClick={() => {
                    previewMutation.mutate(undefined, {
                      onSuccess: () => setConfirmOpen(true),
                    });
                  }}
                >
                  {t("handover.portal.detail.nextBatch")}
                </Button>
                <span className="text-caption text-ink-faint">{t("handover.portal.detail.nextBatchHint")}</span>
              </>
            ) : action.allowed_actions.includes("execute") ? (
              <Button
                type="button"
                size="sm"
                variant="primary"
                disabled={allocatorBusy || executeMutation.isPending}
                onClick={() => setConfirmOpen(true)}
              >
                {t("handover.portal.detail.execute")}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {(status === "executing" || status === "async_pending") ? (
        <div className="space-y-2" aria-busy="true">
          <p className="text-body text-ink-soft">{t("handover.portal.detail.executing")}</p>
          <div className="h-16 animate-pulse rounded-[2px] bg-ink/5" />
          <AssetAllocator surface={surface} taskId={task.id} action={action} readOnly />
        </div>
      ) : null}

      {status === "done" && action.summary ? (
        <ul className="grid gap-1 text-body text-ink-soft">
          {Object.entries(action.summary).map(([type, summary]) => (
            <li key={type}>
              <strong className="text-ink">{type}</strong>:{" "}
              {t("handover.portal.detail.summaryTransferred", { count: summary.transferred })}
              {" · "}
              {t("handover.portal.detail.summaryReleased", { count: summary.released })}
              {" · "}
              {t("handover.portal.detail.summarySkipped", { count: summary.skipped })}
              {(summary.merged > 0 || summary.failed > 0) && (
                <>
                  {" · "}
                  {t("handover.portal.detail.summaryMerged", { count: summary.merged })}
                  {" · "}
                  {t("handover.portal.detail.summaryFailed", { count: summary.failed })}
                </>
              )}
            </li>
          ))}
        </ul>
      ) : null}

      {status === "failed" ? (
        <div className="space-y-2">
          <p className="text-body font-medium text-ink">
            {action.data_completed_at
              ? t("handover.portal.detail.failedGrantPending")
              : t("handover.portal.detail.failedDataPending")}
          </p>
          {action.last_error ? <p className="text-caption text-signal">{action.last_error}</p> : null}
          <div className="flex flex-wrap gap-2">
            {action.allowed_actions.includes("retry") ? (
              <Button type="button" size="sm" loading={retryMutation.isPending} onClick={() => retryMutation.mutate()}>
                {t("handover.portal.detail.retry")}
              </Button>
            ) : null}
            {action.allowed_actions.includes("skip") && isConsoleSuperuser ? (
              <Button type="button" size="sm" variant="ghost-danger" onClick={() => setSkipOpen(true)}>
                {t("handover.console.skip")}
              </Button>
            ) : null}
            {!action.allowed_actions.includes("retry") && !action.allowed_actions.includes("skip") ? (
              <p className="text-body text-ink-soft">{t("handover.portal.detail.notRetryable")}</p>
            ) : null}
            {isConsoleSuperuser && surface === "console" ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={async () => {
                  const payload = await apiRequest<{ last_error_raw: string }>(
                    handoverActionPath("console", task.id, action.app_key, "errors/raw"),
                  );
                  setRawError(payload.last_error_raw);
                }}
              >
                {t("handover.console.viewRawError")}
              </Button>
            ) : null}
          </div>
          {rawError ? <pre className="max-h-40 overflow-auto text-caption text-ink-faint">{rawError}</pre> : null}
        </div>
      ) : null}

      {confirmOpen ? (
        <Dialog
          title={t("handover.portal.detail.executeConfirmTitle")}
          size="sm"
          onClose={() => setConfirmOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setConfirmOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="primary"
                loading={executeMutation.isPending}
                onClick={() => executeMutation.mutate()}
              >
                {t("handover.portal.detail.executeConfirm")}
              </Button>
            </>
          }
        >
          <p className="text-body leading-5 text-ink-soft" data-testid="execute-confirm-body">
            {confirmParts.uniqueReceiverNames.length > 1
              ? t("handover.portal.detail.executeConfirmBodyMulti", {
                  assets: confirmParts.transferLines.join("、") || "-",
                  count: confirmParts.uniqueReceiverNames.length,
                  overrides: confirmParts.overrideCount,
                })
              : t("handover.portal.detail.executeConfirmBody", {
                  assets: confirmParts.transferLines.join("、") || "-",
                  receiver: primaryReceiver,
                  overrides: confirmParts.overrideCount,
                })}
          </p>
        </Dialog>
      ) : null}

      {skipOpen ? (
        <Dialog
          title={t("handover.console.skipTitle")}
          size="sm"
          onClose={() => setSkipOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setSkipOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={skipReason.trim().length < 10}
                loading={skipMutation.isPending}
                onClick={() => skipMutation.mutate()}
              >
                {t("handover.console.skipConfirm")}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-body text-signal">{t("handover.console.skipWarning")}</p>
            <TextArea
              value={skipReason}
              aria-label={t("handover.console.skipReason")}
              onChange={(event) => setSkipReason(event.currentTarget.value)}
            />
          </div>
        </Dialog>
      ) : null}

      {asyncAbandonOpen ? (
        <Dialog
          title={t("handover.console.asyncAbandonTitle")}
          size="sm"
          onClose={() => setAsyncAbandonOpen(false)}
          footer={
            <>
              <Button type="button" onClick={() => setAsyncAbandonOpen(false)}>
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                variant="danger"
                disabled={asyncReason.trim().length < 10}
                loading={asyncAbandonMutation.isPending}
                onClick={() => asyncAbandonMutation.mutate()}
              >
                {t("handover.console.asyncAbandonConfirm")}
              </Button>
            </>
          }
        >
          <div className="space-y-3">
            <p className="text-body text-ink-soft">{t("handover.console.asyncAbandonHint")}</p>
            <Field label={t("handover.console.asyncAbandonOutcome")}>
              <SelectInput
                value={asyncOutcome}
                aria-label={t("handover.console.asyncAbandonOutcome")}
                onChange={(event) => setAsyncOutcome(event.currentTarget.value as "done" | "failed")}
              >
                <option value="done">{t("handover.console.asyncAbandonOutcomeDone")}</option>
                <option value="failed">{t("handover.console.asyncAbandonOutcomeFailed")}</option>
              </SelectInput>
            </Field>
            <Field label={t("handover.console.asyncAbandonReason")} hint={t("handover.portal.reassign.reasonHint")}>
              <TextArea
                value={asyncReason}
                aria-label={t("handover.console.asyncAbandonReason")}
                onChange={(event) => setAsyncReason(event.currentTarget.value)}
              />
            </Field>
          </div>
        </Dialog>
      ) : null}

      {poll ? (
        <PollMarker
          onTick={() => {
            void queryClient.invalidateQueries({ queryKey: ["handover", "task", surface, String(task.id)] });
            onTaskRefresh();
          }}
        />
      ) : null}
    </li>
  );
}

function PollMarker({ onTick }: { onTick: () => void }) {
  useEffect(() => {
    const id = window.setInterval(onTick, 3000);
    return () => window.clearInterval(id);
  }, [onTick]);
  return null;
}

function handleActionError(
  error: Error,
  setBanner: (msg: string | null) => void,
  t: ReturnType<typeof useI18n>["t"],
  onTaskRefresh: () => void,
  setConfirmOpen: (open: boolean) => void,
) {
  const reason = apiErrorReason(error);
  if (reason === "snapshot_stale") {
    setBanner(t("handover.portal.detail.snapshotStale"));
    setConfirmOpen(false);
    onTaskRefresh();
    return;
  }
  if (reason === "downstream_locked") {
    setBanner(t("handover.portal.detail.downstreamLocked"));
    setConfirmOpen(false);
    onTaskRefresh();
    return;
  }
  // 409 confirm_version_stale：刷新详情并用新 confirm_version 重新确认（01 §6.1）
  if (reason === "confirm_version_stale") {
    setBanner(t("handover.portal.detail.confirmVersionStale"));
    onTaskRefresh();
    setConfirmOpen(true);
    return;
  }
  // 413 payload_too_large：action 保持 previewed 并返回 batch_progress，刷新后出现 [执行下一批]
  if (reason === "payload_too_large") {
    setBanner(t("handover.portal.detail.payloadTooLarge"));
    setConfirmOpen(false);
    onTaskRefresh();
    return;
  }
  setConfirmOpen(false);
  setBanner(error.message);
}

function resolveConfirmReceiver(
  confirmParts: ReturnType<typeof buildExecuteConfirmParts>,
  action: HandoverAction,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (confirmParts.uniqueReceiverNames.length > 1) {
    return t("handover.portal.detail.multiReceivers", { count: confirmParts.uniqueReceiverNames.length });
  }
  if (confirmParts.uniqueReceiverNames.length === 1) {
    return confirmParts.uniqueReceiverNames[0];
  }
  return action.grant_receiver?.name || "-";
}

function resolveSkipDisplay(
  action: HandoverAction,
  t: ReturnType<typeof useI18n>["t"],
  fmt: (value: string | null | undefined) => string,
): string {
  const latest = action.skip_history[action.skip_history.length - 1];
  const who = action.skipped_by || latest?.actor_id || "";
  const when = action.skipped_at || latest?.skipped_at || null;
  const reason = action.skip_reason || latest?.reason || "";
  if (!who && !when && action.skip_history.length === 0) {
    return t("handover.portal.detail.skipMissingActor");
  }
  if (!who && latest) {
    return t("handover.portal.detail.skippedBy", {
      who: latest.actor_id,
      when: fmt(latest.skipped_at),
      reason: latest.reason,
    });
  }
  if (!who) {
    return t("handover.portal.detail.skipMissingActor");
  }
  return t("handover.portal.detail.skippedBy", {
    who,
    when: when ? fmt(when) : "-",
    reason,
  });
}

function actionStatusLabel(t: ReturnType<typeof useI18n>["t"], status: HandoverAction["status"]): string {
  switch (status) {
    case "pending":
      return t("handover.actionStatus.pending");
    case "previewed":
      return t("handover.actionStatus.previewed");
    case "executing":
      return t("handover.actionStatus.executing");
    case "async_pending":
      return t("handover.actionStatus.asyncPending");
    case "done":
      return t("handover.actionStatus.done");
    case "failed":
      return t("handover.actionStatus.failed");
    case "skipped":
      return t("handover.actionStatus.skipped");
    case "blocked":
      return t("handover.actionStatus.blocked");
    case "async_attention_required":
      return t("handover.actionStatus.asyncAttentionRequired");
    default:
      return status;
  }
}

function actionStatusBadgeTone(
  status: HandoverAction["status"],
): "neutral" | "amber" | "evergreen" | "signal" | "bond" | "faint" {
  switch (status) {
    case "done":
      return "evergreen";
    case "failed":
    case "blocked":
      return "signal";
    case "executing":
    case "async_pending":
    case "async_attention_required":
      return "amber";
    case "previewed":
      return "bond";
    case "skipped":
      return "faint";
    default:
      return "neutral";
  }
}
