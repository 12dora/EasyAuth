import { getCoreRowModel, getPaginationRowModel, useReactTable } from "@tanstack/react-table";
import { Plus } from "lucide-react";

import { Button } from "../../../../components/Button";
import { StatusBanner } from "../../../../components/StatusBanner";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { useI18n } from "../../../../i18n/I18nProvider";
import { AuthorizationGroupDialog } from "../matrix/AuthorizationGroupDialog";
import { authorizationGroupColumns } from "../matrix/matrixColumns";
import { useAuthorizationGroupDraft } from "../matrix/useAuthorizationGroupDraft";
import { useMatrixQueries } from "../matrix/useMatrixQueries";
import { TableView } from "../../../../components/ui/TableView";

export function MatrixTab({ appKey, canManage = true }: { appKey: string; canManage?: boolean }) {
  const { t } = useI18n();
  const { groupsQueryKey, groupsQuery, permissionsQuery, scopesQuery, authorizationGroups, permissions, activeScopes } = useMatrixQueries(appKey);
  const draft = useAuthorizationGroupDraft({ appKey, groupsQueryKey, permissions, activeScopes });
  const authorizationGroupTable = useReactTable({
    data: authorizationGroups,
    columns: authorizationGroupColumns({ t, canManage, onEdit: draft.openEdit }),
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.matrix.heading")}</h2>
        <Button type="button" variant="primary" icon={<Plus size={16} />} onClick={draft.openCreate} disabled={!canManage}>
          {t("common.new")}
        </Button>
      </div>
      {groupsQuery.error ? <StatusBanner live="alert" tone="signal" title={t("console.matrix.groupsLoadFailed")} message={groupsQuery.error.message} /> : null}
      {permissionsQuery.error ? <StatusBanner live="alert" tone="signal" title={t("console.matrix.permissionsLoadFailed")} message={permissionsQuery.error.message} /> : null}
      {scopesQuery.error ? <StatusBanner live="alert" tone="signal" title={t("console.matrix.scopesLoadFailed")} message={scopesQuery.error.message} /> : null}
      <TableView
        table={authorizationGroupTable}
        totalItems={authorizationGroups.length}
        isLoading={groupsQuery.isLoading}
        empty={<EmptyState title={t("console.matrix.groupsEmpty")} description={t("console.matrix.groupsEmptyDescription")} />}
      />
      {draft.groupDialogOpen ? (
        <AuthorizationGroupDialog
          isEditing={Boolean(draft.selectedKey)}
          canManage={canManage}
          form={draft.form}
          setForm={draft.setForm}
          permissions={permissions}
          scopeOptions={draft.scopeOptions}
          grantPermission={draft.grantPermission}
          setGrantPermission={draft.setGrantPermission}
          grantScope={draft.grantScope}
          setGrantScope={draft.setGrantScope}
          addGrant={draft.addGrant}
          isSaving={draft.saveMutation.isPending}
          onSave={() => draft.saveMutation.mutate()}
          onClose={draft.closeDialog}
        />
      ) : null}
    </section>
  );
}
