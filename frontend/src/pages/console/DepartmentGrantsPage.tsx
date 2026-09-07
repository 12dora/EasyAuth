import { Plus, RefreshCcw } from "lucide-react";
import { useCallback } from "react";

import { Button } from "../../components/Button";
import { TextInput } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { PageState } from "../../components/ui/PageState";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { OrgTree } from "../../features/orgTree/OrgTree";
import { useI18n } from "../../i18n/I18nProvider";
import { ApiError } from "../../lib/api";
import { departmentDisplayName } from "../../lib/departmentDisplayName";
import type { DepartmentSummary, OrgTreeNode } from "../../lib/domain/departmentGrants";
import { DepartmentGrantEditorDialog } from "./DepartmentGrantEditorDialog";
import { DepartmentGrantPolicyTable } from "./DepartmentGrantPolicyTable";
import { apiErrorDetailMessages, useDepartmentGrants } from "./useDepartmentGrants";

export function DepartmentGrantsPage() {
  const { t } = useI18n();
  const page = useDepartmentGrants();
  const { deleteMutation, deleteTarget, department, editor, policies, policiesQuery, saveMutation, tree, treeQuery } = page;

  // 根部门在钉钉镜像里没有名字, 树、右栏与弹窗都得走同一份兜底文案。
  const departmentLabel = useCallback((node: OrgTreeNode) => departmentDisplayName(node, t), [t]);
  const treeError = treeQuery.error;
  const directoryNotSynced = treeError instanceof ApiError && treeError.status === 409;

  return (
    <>
      <PageHeader
        eyebrow={t("departmentGrants.eyebrow")}
        title={t("departmentGrants.title")}
        description={t("departmentGrants.description")}
        actions={
          <>
            <Button
              icon={<RefreshCcw size={16} />}
              loading={treeQuery.isFetching || policiesQuery.isFetching}
              onClick={() => {
                void treeQuery.refetch();
                void policiesQuery.refetch();
              }}
            >
              {t("common.refresh")}
            </Button>
            <Button
              type="button"
              variant="primary"
              icon={<Plus size={16} />}
              disabled={!page.selectedDeptId}
              onClick={() => page.openEditor(null)}
            >
              {t("departmentGrants.create")}
            </Button>
          </>
        }
      />

      {directoryNotSynced ? (
        <PageState
          tone="amber"
          title={t("departmentGrants.tree.notSyncedTitle")}
          description={t("departmentGrants.tree.notSyncedDescription")}
        />
      ) : treeError ? (
        <PageState
          tone="signal"
          title={t("departmentGrants.tree.loadFailed")}
          description={treeError.message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={treeQuery.isFetching} onClick={() => void treeQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[minmax(16rem,22rem)_1fr]">
          <PanelSurface padding="sm" className="self-start">
            <TextInput
              value={page.treeFilter}
              onChange={(event) => page.setTreeFilter(event.target.value)}
              aria-label={t("departmentGrants.tree.searchLabel")}
              placeholder={t("departmentGrants.tree.searchPlaceholder")}
            />
            <div className="mt-3 max-h-[34rem] overflow-y-auto">
              {tree ? (
                <OrgTree
                  root={tree.root}
                  selectedDeptId={page.selectedDeptId}
                  expandedDeptIds={page.expandedDeptIds}
                  onSelect={page.selectDepartment}
                  onExpandedChange={page.setExpandedDeptIds}
                  filter={page.treeFilter}
                  labelFor={departmentLabel}
                />
              ) : (
                <p className="px-2 py-3 text-caption text-ink-faint" role="status">
                  {t("departmentGrants.tree.loading")}
                </p>
              )}
            </div>
          </PanelSurface>

          <div className="min-w-0 space-y-4">
            {department ? <DepartmentHeading department={department} /> : null}
            {policiesQuery.error && policies.length > 0 ? (
              <StatusBanner
                live="alert"
                tone="signal"
                title={t("departmentGrants.loadFailed")}
                message={policiesQuery.error.message}
              />
            ) : null}
            {policiesQuery.error && policies.length === 0 ? (
              <PageState
                tone="signal"
                title={t("departmentGrants.loadFailed")}
                description={policiesQuery.error.message}
                action={
                  <Button
                    icon={<RefreshCcw size={16} />}
                    loading={policiesQuery.isFetching}
                    onClick={() => void policiesQuery.refetch()}
                  >
                    {t("common.retry")}
                  </Button>
                }
              />
            ) : !page.selectedDeptId ? (
              <PageState
                title={t("departmentGrants.selectDepartment.title")}
                description={t("departmentGrants.selectDepartment.description")}
              />
            ) : (
              <DepartmentGrantPolicyTable
                policies={policies}
                isLoading={policiesQuery.isLoading}
                onEdit={page.openEditor}
                onDelete={page.setDeleteTarget}
              />
            )}
          </div>
        </div>
      )}

      {editor ? (
        <DepartmentGrantEditorDialog
          departmentName={department ? departmentDisplayName(department, t) : ""}
          policy={editor.policy}
          errorMessage={saveMutation.error ? saveMutation.error.message : ""}
          errorDetails={apiErrorDetailMessages(saveMutation.error)}
          isSubmitting={saveMutation.isPending}
          onSubmit={page.submitEditor}
          onClose={() => {
            if (!saveMutation.isPending) {
              page.closeEditor();
            }
          }}
        />
      ) : null}

      {deleteTarget ? (
        <ConfirmDialog
          title={t("departmentGrants.delete.title")}
          message={t("departmentGrants.delete.message", { dept: departmentDisplayName(deleteTarget.defined_on, t) })}
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

function DepartmentHeading({ department }: { department: DepartmentSummary }) {
  const { t } = useI18n();

  return (
    <div className="space-y-1">
      <p className="text-caption text-ink-faint" aria-label={t("departmentGrants.department.pathAriaLabel")}>
        {department.path.map((item) => departmentDisplayName(item, t)).join(" / ")}
      </p>
      <h2 className="text-lg font-semibold leading-tight text-ink">{departmentDisplayName(department, t)}</h2>
      <p className="text-body leading-5 text-ink-soft">
        {t("departmentGrants.department.memberSummary", {
          direct: department.member_count,
          subtree: department.subtree_member_count,
        })}
      </p>
    </div>
  );
}
