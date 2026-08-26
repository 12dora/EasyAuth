import { RefreshCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../../components/Button";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { PageState } from "../../../components/ui/PageState";
import { useI18n } from "../../../i18n/I18nProvider";
import { HandoverTaskTable } from "./HandoverTaskTable";
import { useHandoverTaskList } from "./useHandoverTaskList";

export function HandoverTaskList() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const page = useHandoverTaskList();
  const { tasksQuery, tasks, deleteTarget, deleteMutation } = page;

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("nav.console.handoverTasks")}
        description={t("handover.list.description")}
        actions={
          <Button icon={<RefreshCcw size={16} />} loading={tasksQuery.isFetching} onClick={() => void tasksQuery.refetch()}>
            {t("common.refresh")}
          </Button>
        }
      />
      {tasksQuery.error && tasks.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("handover.list.loadFailed")} message={(tasksQuery.error as Error).message} />
      ) : null}
      {tasksQuery.error && tasks.length === 0 ? (
        <PageState
          tone="signal"
          title={t("handover.list.loadFailed")}
          description={(tasksQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={tasksQuery.isFetching} onClick={() => void tasksQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <HandoverTaskTable
          tasks={tasks}
          isLoading={tasksQuery.isLoading || tasksQuery.isPlaceholderData}
          tableProps={page.tableProps}
          actions={{
            onOpen: (taskId) => void navigate(`/console/lifecycle/handover-tasks/${taskId}`),
            onDelete: page.setDeleteTarget,
          }}
        />
      )}
      {deleteTarget ? (
        <ConfirmDialog
          title={t("handover.list.deleteTitle")}
          message={t("handover.list.deleteMessage", {
            name: deleteTarget.subject.name || deleteTarget.subject.user_id,
          })}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => page.setDeleteTarget(null)}
        />
      ) : null}
    </>
  );
}
