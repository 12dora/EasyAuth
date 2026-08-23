import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { useToast } from "../../../../components/ui/Toast";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { AppScopeItem, AuthorizationGroupItem, PermissionItem } from "../../../../lib/domain";
import { invalidateAppCatalogQueries } from "../invalidateAppQueries";
import { buildAuthorizationGroupPayload, grantKey, normalizeGrants } from "./grantDraft";
import type { AuthorizationGroupForm } from "./grantFormUpdates";
import { inheritManagedScopePolicy } from "./managedScopePolicy";

export const emptyGroupForm: AuthorizationGroupForm = {
  key: "",
  kind: "role",
  name: "",
  description: "",
  requestable: true,
  is_active: true,
  grants: [],
};

/** 授权组新建/编辑草稿: 表单、可选授权项联动、追加授权项与保存。 */
export function useAuthorizationGroupDraft({
  appKey,
  groupsQueryKey,
  permissions,
  activeScopes,
}: {
  appKey: string;
  groupsQueryKey: unknown[];
  permissions: PermissionItem[];
  activeScopes: AppScopeItem[];
}) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [selectedKey, setSelectedKey] = useState("");
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [form, setForm] = useState<AuthorizationGroupForm>(emptyGroupForm);
  const [grantPermission, setGrantPermission] = useState("");
  const [grantScope, setGrantScope] = useState("");
  const scopeOptions = useMemo(
    () =>
      activeScopes.filter((scope) => {
        const permission = permissions.find((item) => item.key === grantPermission);
        return !permission?.supported_scopes?.length || permission.supported_scopes.includes(scope.key);
      }),
    [activeScopes, grantPermission, permissions],
  );

  useEffect(() => {
    if (!grantPermission && permissions[0]?.key) {
      setGrantPermission(permissions[0].key);
    }
  }, [grantPermission, permissions]);

  useEffect(() => {
    if (!grantScope && scopeOptions[0]?.key) {
      setGrantScope(scopeOptions[0].key);
    }
    if (grantScope && scopeOptions.length > 0 && !scopeOptions.some((scope) => scope.key === grantScope)) {
      setGrantScope(scopeOptions[0].key);
    }
  }, [grantScope, scopeOptions]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = buildAuthorizationGroupPayload(form);
      const method = selectedKey ? "PATCH" : "POST";
      const url = selectedKey
        ? `/console/api/v1/apps/${appKey}/authorization-groups/${selectedKey}`
        : `/console/api/v1/apps/${appKey}/authorization-groups`;
      return apiRequest(url, { method, body: payload });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: groupsQueryKey });
      invalidateAppCatalogQueries(queryClient, appKey);
      setGroupDialogOpen(false);
      setSelectedKey("");
      setForm(emptyGroupForm);
    },
    onError: (error: Error) => {
      toast.error(t("console.matrix.saveFailed"), error.message);
    },
  });

  const addGrant = () => {
    if (!grantPermission || !grantScope) {
      return;
    }
    setForm((current) => {
      if (current.grants.some((grant) => grantKey(grant.permission, grant.scope) === grantKey(grantPermission, grantScope))) {
        return current;
      }
      return {
        ...current,
        grants: [...current.grants, {
          permission: grantPermission,
          scope: grantScope,
          is_active: true,
          ...(grantScope === "MANAGED_USERS" ? { managed_scope_policy: inheritManagedScopePolicy() } : {}),
        }],
      };
    });
  };

  const openCreate = () => {
    setSelectedKey("");
    setForm(emptyGroupForm);
    setGroupDialogOpen(true);
  };

  const openEdit = (group: AuthorizationGroupItem) => {
    setSelectedKey(group.key);
    setForm({ ...group, description: group.description ?? "", grants: normalizeGrants(group.grants ?? []) });
    setGroupDialogOpen(true);
  };

  return {
    selectedKey,
    groupDialogOpen,
    closeDialog: () => setGroupDialogOpen(false),
    openCreate,
    openEdit,
    form,
    setForm,
    grantPermission,
    setGrantPermission,
    grantScope,
    setGrantScope,
    scopeOptions,
    addGrant,
    saveMutation,
  };
}
