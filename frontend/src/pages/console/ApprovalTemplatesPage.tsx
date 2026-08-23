import { Plus, RefreshCcw } from "lucide-react";

import { Button } from "../../components/Button";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { PageState } from "../../components/ui/PageState";
import { useI18n } from "../../i18n/I18nProvider";
import { ApprovalTemplateEditorDialog } from "./ApprovalTemplateEditorDialog";
import { ApprovalTemplateTable } from "./ApprovalTemplateTable";
import { ApprovalTemplateTestDialog } from "./ApprovalTemplateTestDialog";
import { useApprovalTemplates } from "./useApprovalTemplates";

export function ApprovalTemplatesPage() {
  const { t } = useI18n();
  const page = useApprovalTemplates();
  const { templatesQuery, templates, editorState, testTemplate, deleteTarget, saveMutation, deleteMutation } = page;

  return (
    <>
      <PageHeader
        eyebrow={t("nav.console.approvalCenter")}
        title={t("nav.console.approvalTemplates")}
        description={t("approvalTemplates.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={() => page.openEditor(null)}>
              {t("approvalTemplates.create")}
            </Button>
          </>
        }
      />
      {templatesQuery.error && templates.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("approvalTemplates.loadFailed")} message={(templatesQuery.error as Error).message} />
      ) : null}
      {templatesQuery.error && templates.length === 0 ? (
        <PageState
          tone="signal"
          title={t("approvalTemplates.loadFailed")}
          description={(templatesQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <ApprovalTemplateTable
          templates={templates}
          isLoading={templatesQuery.isLoading}
          actions={{
            onEdit: page.openEditor,
            onTest: page.setTestTemplate,
            onDelete: page.setDeleteTarget,
          }}
        />
      )}
      {editorState ? (
        <ApprovalTemplateEditorDialog
          template={editorState.template}
          errorMessage={saveMutation.error ? (saveMutation.error as Error).message : ""}
          isSubmitting={saveMutation.isPending}
          onClose={() => {
            if (!saveMutation.isPending) {
              page.closeEditor();
            }
          }}
          onSubmit={(payload) => saveMutation.mutate({ template: editorState.template, payload })}
        />
      ) : null}
      {testTemplate ? <ApprovalTemplateTestDialog template={testTemplate} onClose={() => page.setTestTemplate(null)} /> : null}
      {deleteTarget ? (
        <ConfirmDialog
          title={t("approvalTemplates.deleteTitle")}
          message={t("approvalTemplates.deleteMessage", { name: deleteTarget.name })}
          confirmLabel={t("common.delete")}
          confirming={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate(deleteTarget)}
          onClose={() => {
            if (!deleteMutation.isPending) {
              page.setDeleteTarget(null);
            }
          }}
        />
      ) : null}
    </>
  );
}
