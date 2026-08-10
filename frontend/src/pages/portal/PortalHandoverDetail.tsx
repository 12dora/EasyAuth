import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PageState } from "../../components/ui/PageState";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { HandoverActionPanel } from "../../features/handover/HandoverActionPanel";
import { daysLeftTone } from "../../features/handover/surface";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { HandoverAction, HandoverTaskDetail, HandoverTaskPayload } from "../../lib/domain";

export function PortalHandoverDetail() {
  const { t } = useI18n();
  const { taskId = "" } = useParams();
  const queryClient = useQueryClient();
  const detailQueryKey = ["handover", "task", "portal", taskId];

  const taskQuery = useQuery({
    queryKey: detailQueryKey,
    queryFn: () => apiRequest<HandoverTaskPayload>(`/portal/api/v1/handover-tasks/${taskId}`),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const task = query.state.data?.handover_task;
      if (!task) {
        return false;
      }
      const busy = task.actions.some((action) => action.status === "executing" || action.status === "async_pending");
      return busy ? 3000 : false;
    },
  });

  const task = taskQuery.data?.handover_task;

  const replaceAction = (next: HandoverAction) => {
    queryClient.setQueryData<HandoverTaskPayload>(detailQueryKey, (current) => {
      if (!current?.handover_task) {
        return current;
      }
      return {
        handover_task: {
          ...current.handover_task,
          actions: current.handover_task.actions.map((action) =>
            action.app_key === next.app_key ? next : action,
          ),
        },
      };
    });
  };

  if (taskQuery.error && !task) {
    return (
      <PageState
        tone="signal"
        title={t("handover.portal.detail.loadFailed")}
        description={(taskQuery.error as Error).message}
        action={
          <Button type="button" onClick={() => void taskQuery.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={t("shell.portal.title")}
        title={task ? `${kindLabel(t, task.kind)} · ${task.subject.name || task.subject.user_id}` : t("handover.portal.detail.title")}
        description={task?.reason || undefined}
        actions={<ButtonLink to="/portal/handovers">{t("handover.portal.detail.back")}</ButtonLink>}
      />
      {taskQuery.error && task ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("handover.portal.detail.loadFailed")}
          message={(taskQuery.error as Error).message}
        />
      ) : null}
      {task ? <DetailBody task={task} onActionReplace={replaceAction} onRefresh={() => void taskQuery.refetch()} /> : null}
    </>
  );
}

function DetailBody({
  task,
  onActionReplace,
  onRefresh,
}: {
  task: HandoverTaskDetail;
  onActionReplace: (action: HandoverAction) => void;
  onRefresh: () => void;
}) {
  const { t } = useI18n();
  const daysLeft = task.escalation.days_left;
  const daysTone = daysLeftTone(daysLeft);

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="bond">{kindLabel(t, task.kind)}</Badge>
          <Badge tone="neutral">{taskStatusLabel(t, task.status)}</Badge>
          {task.escalation.deadline == null ? (
            <Badge tone="neutral">{t("handover.portal.list.awaitingSuperuser")}</Badge>
          ) : (
            <Badge tone={daysTone}>{t("handover.portal.detail.daysLeft", { count: daysLeft ?? 0 })}</Badge>
          )}
          {task.escalation_level > 0 ? (
            <Badge tone="amber">{t("handover.portal.detail.escalated", { count: task.escalation_level })}</Badge>
          ) : null}
        </div>
        <dl className="grid gap-2 text-body sm:grid-cols-2">
          <div>
            <dt className="text-caption text-ink-faint">{t("handover.detail.subject")}</dt>
            <dd className="m-0 font-medium text-ink">{task.subject.name || task.subject.user_id}</dd>
          </div>
          <div>
            <dt className="text-caption text-ink-faint">{t("handover.portal.detail.assignee")}</dt>
            <dd className="m-0 font-medium text-ink">
              {task.assignee?.name || task.assignee?.user_id || t("handover.assigneeState.superuser_pool")}
            </dd>
          </div>
        </dl>
      </PanelSurface>
      <ul className="grid gap-3">
        {task.actions.map((action) => (
          <HandoverActionPanel
            key={action.app_key}
            surface="portal"
            task={task}
            action={action}
            onTaskRefresh={onRefresh}
            onActionReplace={onActionReplace}
          />
        ))}
      </ul>
    </section>
  );
}

function kindLabel(t: ReturnType<typeof useI18n>["t"], kind: string): string {
  switch (kind) {
    case "offboard":
      return t("handover.kind.offboard");
    case "transfer":
      return t("handover.kind.transfer");
    case "pre_offboard":
      return t("handover.kind.pre_offboard");
    case "reassign":
      return t("handover.kind.reassign");
    default:
      return kind;
  }
}

function taskStatusLabel(t: ReturnType<typeof useI18n>["t"], status: string): string {
  switch (status) {
    case "pending":
      return t("handover.taskStatus.pending");
    case "in_progress":
      return t("handover.taskStatus.inProgress");
    case "completed":
      return t("handover.taskStatus.completed");
    case "cancelled":
      return t("handover.taskStatus.cancelled");
    default:
      return status;
  }
}
