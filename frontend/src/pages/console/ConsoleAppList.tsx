import { Compass, Plus, RefreshCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { PageState } from "../../components/ui/PageState";
import { useI18n } from "../../i18n/I18nProvider";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { ConsoleAppCreateDialog } from "./ConsoleAppCreateDialog";
import { ConsoleAppTable } from "./ConsoleAppTable";
import { useConsoleAppList } from "./useConsoleAppList";

export function ConsoleAppList() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const page = useConsoleAppList();
  const { appsQuery, apps, deleteTarget, createMutation, deleteMutation } = page;

  return (
    <>
      <PageHeader
        eyebrow={t("appList.eyebrow")}
        title={t("appList.title")}
        description={t("appList.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={appsQuery.isFetching} onClick={() => void appsQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" icon={<Plus size={16} />} onClick={() => page.setCreateDialogOpen(true)}>
              {t("appList.quickCreate")}
            </Button>
            <Button type="button" variant="primary" icon={<Compass size={16} />} onClick={() => void navigate("/console/apps/new")}>
              {t("appList.onboardingWizard")}
            </Button>
          </>
        }
      />
      {appsQuery.error && apps.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("appList.loadFailed")} message={(appsQuery.error as Error).message} />
      ) : null}
      {appsQuery.error && apps.length === 0 ? (
        <PageState
          tone="signal"
          title={t("appList.loadFailed")}
          description={(appsQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={appsQuery.isFetching} onClick={() => void appsQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <section className="space-y-3">
          <ConsoleAppTable
            apps={apps}
            isLoading={appsQuery.isLoading || appsQuery.isPlaceholderData}
            tableProps={page.tableProps}
            filters={page.filters}
            sort={page.sort}
            actions={{
              togglePending: page.updateStatusMutation.isPending,
              deletePending: deleteMutation.isPending,
              onToggleActive: (app) =>
                page.updateStatusMutation.mutate({ appKey: app.app_key, isActive: !app.is_active }),
              onDelete: page.setDeleteTarget,
              onNavigate: (path) => void navigate(path),
            }}
          />
        </section>
      )}
      {page.createDialogOpen ? (
        <ConsoleAppCreateDialog
          errorMessage={createMutation.error ? (createMutation.error as Error).message : ""}
          isSubmitting={createMutation.isPending}
          onClose={() => page.setCreateDialogOpen(false)}
          onSubmit={(payload) => createMutation.mutate(payload)}
        />
      ) : null}
      {deleteTarget ? (
        <ConfirmDialog
          title={`${t("common.delete")} ${formatAppDisplayName(deleteTarget)}`}
          message={`${t("console.overview.field.appName")}: ${deleteTarget.name}; ${t("console.overview.field.appKey")}: ${deleteTarget.app_key}`}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => page.setDeleteTarget(null)}
        />
      ) : null}
    </>
  );
}
