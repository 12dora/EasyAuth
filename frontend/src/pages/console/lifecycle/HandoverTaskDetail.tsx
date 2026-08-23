import { ArrowRight, RefreshCcw } from "lucide-react";
import { useOutletContext, useParams } from "react-router-dom";

import type { AppShellOutletContext } from "../../../components/AppShell";
import { Button } from "../../../components/Button";
import { ButtonLink } from "../../../components/ButtonLink";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { HandoverActionPanel } from "../../../features/handover/HandoverActionPanel";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverTaskDetail as HandoverTaskDetailRow } from "../../../lib/domain";
import {
  consoleViewerFlags,
  hasActionableApps,
  isOpenTask,
  taskDetailTitle,
  taskSubjectName,
} from "./handoverTaskDetailModel";
import { TaskDetailDialogs } from "./HandoverTaskDialogs";
import { AssigneePanel, SubjectPanel } from "./HandoverTaskOverview";
import { HandoverWizard } from "./HandoverWizard";
import { TeamAdjustSection } from "./TeamAdjustSection";
import { TransferGrantSection } from "./TransferGrantSection";
import { useHandoverTaskDetail } from "./useHandoverTaskDetail";

export function HandoverTaskDetail() {
  const { t } = useI18n();
  const { taskId = "" } = useParams();
  const { isSuperuser, isLocalAdmin } = consoleViewerFlags(useOutletContext<AppShellOutletContext | null>());
  const detail = useHandoverTaskDetail(taskId);
  const { task, taskQuery } = detail;

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

  const openTask = isOpenTask(task);
  const subjectName = taskSubjectName(task);

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={taskDetailTitle(t, task, subjectName)}
        description={task?.reason || undefined}
        actions={
          <HeaderActions
            task={task}
            openTask={openTask}
            onCancelTask={detail.openCancelConfirm}
            onDeleteTask={detail.openDeleteConfirm}
            onContinue={detail.openWizard}
          />
        }
      />
      {taskQuery.error && task ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("handover.detail.loadFailed")}
          message={(taskQuery.error as Error).message}
        />
      ) : null}
      {task ? (
        <TaskDetailBody
          task={task}
          taskId={taskId}
          detail={detail}
          openTask={openTask}
          subjectName={subjectName}
          isSuperuser={isSuperuser}
          isLocalAdmin={isLocalAdmin}
        />
      ) : null}

      {detail.wizardOpen && task ? <HandoverWizard task={task} onClose={detail.closeWizard} /> : null}

      <TaskDetailDialogs detail={detail} subjectName={subjectName} />
    </>
  );
}

function TaskDetailBody({
  task,
  taskId,
  detail,
  openTask,
  subjectName,
  isSuperuser,
  isLocalAdmin,
}: {
  task: HandoverTaskDetailRow;
  taskId: string;
  detail: ReturnType<typeof useHandoverTaskDetail>;
  openTask: boolean;
  subjectName: string;
  isSuperuser: boolean;
  isLocalAdmin: boolean;
}) {
  return (
    <section className="space-y-6">
      <SubjectPanel task={task} subjectName={subjectName} />

      <AssigneePanel
        task={task}
        isLocalAdmin={isLocalAdmin}
        claimPending={detail.claimMutation.isPending}
        onDefer={detail.openDefer}
        onClaim={() => detail.claimMutation.mutate()}
      />

      <AppsPanel
        task={task}
        isSuperuser={isSuperuser}
        isLocalAdmin={isLocalAdmin}
        onTaskRefresh={detail.invalidateDetail}
        onActionReplace={detail.replaceAction}
      />

      {task.kind === "transfer" ? (
        <TransferGrantSection task={task} taskId={taskId} onChanged={detail.invalidateDetail} canOperate={openTask} />
      ) : null}
      {task.kind === "transfer" || task.team_items.length > 0 ? (
        <TeamAdjustSection task={task} taskId={taskId} onChanged={detail.invalidateDetail} canOperate={openTask} />
      ) : null}
    </section>
  );
}

function HeaderActions({
  task,
  openTask,
  onCancelTask,
  onDeleteTask,
  onContinue,
}: {
  task: HandoverTaskDetailRow | undefined;
  openTask: boolean;
  onCancelTask: () => void;
  onDeleteTask: () => void;
  onContinue: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-2">
      <ButtonLink to="/console/lifecycle/handover-tasks">{t("handover.detail.backToList")}</ButtonLink>
      {openTask ? (
        <>
          <Button type="button" variant="ghost-danger" onClick={onCancelTask}>
            {t("handover.detail.cancelTask")}
          </Button>
          <Button
            type="button"
            variant="primary"
            icon={<ArrowRight size={16} />}
            disabled={!hasActionableApps(task)}
            onClick={onContinue}
          >
            {t("handover.continue")}
          </Button>
        </>
      ) : null}
      {task?.status === "cancelled" ? (
        <Button type="button" variant="ghost-danger" onClick={onDeleteTask}>
          {t("handover.detail.deleteTask")}
        </Button>
      ) : null}
    </div>
  );
}

function AppsPanel({
  task,
  isSuperuser,
  isLocalAdmin,
  onTaskRefresh,
  onActionReplace,
}: {
  task: HandoverTaskDetailRow;
  isSuperuser: boolean;
  isLocalAdmin: boolean;
  onTaskRefresh: () => void;
  onActionReplace: ReturnType<typeof useHandoverTaskDetail>["replaceAction"];
}) {
  const { t } = useI18n();
  return (
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
              onTaskRefresh={onTaskRefresh}
              onActionReplace={onActionReplace}
            />
          ))}
        </ul>
      )}
    </PanelSurface>
  );
}
