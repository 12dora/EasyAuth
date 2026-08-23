/** 编排目录查询、表格区块和编辑弹窗。 */

import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import {
  emptyGroupForm,
  emptyPermissionForm,
  emptyScopeForm,
  groupFormFromItem,
  permissionFormFromItem,
  scopeFormFromItem,
} from "../catalog/catalogModel";
import { GroupDialog, PermissionDialog, ScopeDialog } from "../catalog/CatalogDialogs";
import { CatalogGroupsPanel, CatalogPermissionsPanel, CatalogScopesPanel } from "../catalog/CatalogPanels";
import { useCatalogData } from "../catalog/useCatalogData";
import { useCatalogForms } from "../catalog/useCatalogForms";

export function CatalogTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const data = useCatalogData(appKey);
  const forms = useCatalogForms(appKey);
  const closeDialog = () => forms.setActiveDialog(null);

  return (
    <section className="space-y-6">
      {data.treeQuery.error || data.groupsQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("console.catalog.groupsLoadFailed")} message={((data.treeQuery.error ?? data.groupsQuery.error) as Error).message} />
      ) : null}
      {data.scopesQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("console.catalog.scopesLoadFailed")} message={(data.scopesQuery.error as Error).message} />
      ) : null}
      {data.permissionsQuery.error ? (
        <StatusBanner live="alert" tone="signal" title={t("console.catalog.permissionsLoadFailed")} message={(data.permissionsQuery.error as Error).message} />
      ) : null}
      <div className="grid gap-6 xl:grid-cols-2">
        <CatalogGroupsPanel
          rows={data.groupRows}
          isLoading={data.treeQuery.isLoading || data.groupsQuery.isLoading}
          onCreate={() => {
            forms.setGroupForm(emptyGroupForm);
            forms.setEditingGroupKey("");
            forms.setActiveDialog("group");
          }}
          onEdit={(group) => {
            forms.setEditingGroupKey(group.key);
            forms.setGroupForm(groupFormFromItem(group));
            forms.setActiveDialog("group");
          }}
        />
        <CatalogScopesPanel
          scopes={data.scopes}
          isLoading={data.scopesQuery.isLoading}
          togglePending={forms.toggleScopeMutation.isPending}
          onCreate={() => {
            forms.setScopeForm(emptyScopeForm);
            forms.setEditingScopeKey("");
            forms.setActiveDialog("scope");
          }}
          onEdit={(scope) => {
            forms.setEditingScopeKey(scope.key);
            forms.setScopeForm(scopeFormFromItem(scope));
            forms.setActiveDialog("scope");
          }}
          onToggle={(scope) => forms.toggleScopeMutation.mutate(scope)}
        />
      </div>
      <CatalogPermissionsPanel
        permissions={data.permissions}
        isLoading={data.permissionsQuery.isLoading}
        onCreate={() => {
          forms.setPermissionForm(emptyPermissionForm);
          forms.setEditingPermissionKey("");
          forms.setActiveDialog("permission");
        }}
        onEdit={(permission) => {
          forms.setEditingPermissionKey(permission.key);
          forms.setPermissionForm(permissionFormFromItem(permission));
          forms.setActiveDialog("permission");
        }}
      />
      {forms.activeDialog === "scope" ? (
        <ScopeDialog form={forms.scopeForm} editingKey={forms.editingScopeKey} mutation={forms.saveScopeMutation} onChange={forms.setScopeForm} onClose={closeDialog} />
      ) : null}
      {forms.activeDialog === "group" ? (
        <GroupDialog form={forms.groupForm} groups={data.groups} editingKey={forms.editingGroupKey} mutation={forms.saveGroupMutation} onChange={forms.setGroupForm} onClose={closeDialog} />
      ) : null}
      {forms.activeDialog === "permission" ? (
        <PermissionDialog form={forms.permissionForm} groups={data.groups} editingKey={forms.editingPermissionKey} mutation={forms.savePermissionMutation} onChange={forms.setPermissionForm} onClose={closeDialog} />
      ) : null}
    </section>
  );
}
