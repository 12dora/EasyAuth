import { useEffect } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { cn } from "../../lib/cn";
import type { HandoverAction, HandoverTaskDetail } from "../../lib/domain";
import { AssetAllocator } from "./AssetAllocator";
import { ActionPanelDialogs } from "./HandoverActionDialogs";
import { HandoverActionOutcomeSection } from "./HandoverActionOutcome";
import {
  actionPanelToneClass,
  actionStatusBadgeTone,
  actionStatusLabel,
  resolveSkipDisplay,
} from "./handoverActionPanelModel";
import { HandoverActionPreviewedSection } from "./HandoverActionPreviewedSection";
import type { HandoverSurface } from "./surface";
import { useHandoverActionPanel } from "./useHandoverActionPanel";

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
  const { t } = useI18n();
  const scope = { surface, taskId: task.id, appKey: action.app_key };
  const panel = useHandoverActionPanel({ scope, action, onTaskRefresh, onActionReplace });

  const status = action.status;
  // batch_progress 非 null 期间禁止改分配（02 §4 / 01 batch_plan_in_progress）
  const readOnly = status === "executing" || status === "async_pending" || action.batch_progress != null;
  const poll = status === "executing" || status === "async_pending";
  const isConsoleOperator = isConsoleSuperuser && surface === "console";

  return (
    <li
      className={cn("space-y-3 rounded-[3px] border px-4 py-3", actionPanelToneClass(action))}
      data-testid={`action-panel-${action.app_key}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <strong className="text-body text-ink">
          {formatAppDisplayName({ name: action.app_name, alias: action.app_alias })}
        </strong>
        <Badge tone={actionStatusBadgeTone(status)}>{actionStatusLabel(t, status)}</Badge>
      </div>

      <ActionBanners action={action} banner={panel.banner} />

      <ActionStatusNotice
        action={action}
        isConsoleOperator={isConsoleOperator}
        previewPending={panel.previewMutation.isPending}
        actionMutationLock={panel.actionMutationLock}
        onPreview={() => panel.previewMutation.mutate()}
        onSkip={panel.openSkip}
        onAsyncAbandon={panel.openAsyncAbandon}
      />

      {status === "previewed" ? (
        <HandoverActionPreviewedSection
          scope={scope}
          task={task}
          action={action}
          readOnly={readOnly}
          grantBusy={panel.grantBusy}
          actionMutationLock={panel.actionMutationLock}
          allocatorResetKey={panel.allocatorResetKey}
          previewPending={panel.previewMutation.isPending}
          onPreview={() => panel.previewMutation.mutate()}
          onGrantReceiverChange={(userId) => panel.grantReceiverMutation.mutate(userId)}
          onAllocatorBusyChange={panel.setAllocatorBusy}
          onSnapshotStale={panel.handleSnapshotStale}
          onActionReplace={onActionReplace}
          onExecuteRequest={panel.openConfirm}
          onNextBatch={() => panel.previewMutation.mutate(undefined, { onSuccess: panel.openConfirm })}
        />
      ) : null}

      {poll ? (
        <div className="space-y-2" aria-busy="true">
          <p className="text-body text-ink-soft">{t("handover.portal.detail.executing")}</p>
          <div className="h-16 animate-pulse rounded-[2px] bg-ink/5" />
          <AssetAllocator surface={surface} taskId={task.id} action={action} readOnly />
        </div>
      ) : null}

      <HandoverActionOutcomeSection
        status={status}
        action={action}
        isConsoleSuperuser={isConsoleSuperuser}
        showRawErrorButton={isConsoleOperator}
        rawError={panel.rawError}
        retryPending={panel.retryMutation.isPending}
        onRetry={() => panel.retryMutation.mutate()}
        onSkip={panel.openSkip}
        onLoadRawError={() => void panel.loadRawError()}
      />

      <ActionPanelDialogs action={action} panel={panel} />

      {poll ? <PollMarker onTick={() => panel.pollTick()} /> : null}
    </li>
  );
}

function ActionBanners({ action, banner }: { action: HandoverAction; banner: string | null }) {
  return (
    <>
      {banner ? <StatusBanner live="alert" tone="signal" title={banner} /> : null}
      {action.approval_instance_warning ? (
        <StatusBanner
          live="status"
          tone="amber"
          title={action.approval_instance_warning.message}
          message={action.approval_instance_warning.link}
        />
      ) : null}
    </>
  );
}

/** blocked / skipped / async_attention_required / pending 四种轻量状态提示。 */
function ActionStatusNotice({
  action,
  isConsoleOperator,
  previewPending,
  actionMutationLock,
  onPreview,
  onSkip,
  onAsyncAbandon,
}: {
  action: HandoverAction;
  isConsoleOperator: boolean;
  previewPending: boolean;
  actionMutationLock: boolean;
  onPreview: () => void;
  onSkip: () => void;
  onAsyncAbandon: () => void;
}) {
  const { t, formatDateTime: fmt } = useI18n();
  if (action.status === "blocked") {
    return (
      <>
        <p className="text-body text-ink-soft">{t("handover.portal.detail.blockedBody")}</p>
        {isConsoleOperator ? (
          <Button type="button" variant="ghost-danger" size="sm" onClick={onSkip}>
            {t("handover.console.skip")}
          </Button>
        ) : null}
      </>
    );
  }
  if (action.status === "skipped") {
    return <p className="text-body text-ink-soft">{resolveSkipDisplay(action, t, fmt)}</p>;
  }
  if (action.status === "async_attention_required") {
    return (
      <div className="space-y-2">
        <p className="text-body text-ink-soft">{t("handover.portal.detail.asyncAttention")}</p>
        {isConsoleOperator ? (
          <Button type="button" size="sm" variant="ghost-danger" onClick={onAsyncAbandon}>
            {t("handover.console.asyncAbandon")}
          </Button>
        ) : null}
      </div>
    );
  }
  if (action.status === "pending") {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-body text-ink-soft">{t("handover.portal.detail.notPreviewed")}</span>
        {action.allowed_actions.includes("preview") ? (
          <Button
            type="button"
            size="sm"
            loading={previewPending}
            disabled={actionMutationLock && !previewPending}
            onClick={onPreview}
          >
            {t("handover.portal.detail.preview")}
          </Button>
        ) : null}
      </div>
    );
  }
  return null;
}

function PollMarker({ onTick }: { onTick: () => void }) {
  useEffect(() => {
    const id = window.setInterval(onTick, 3000);
    return () => window.clearInterval(id);
  }, [onTick]);
  return null;
}
