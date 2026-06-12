import { useMutation, useQuery } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type {
  PermissionGroupItem,
  PermissionItem,
  PortalCatalogApp,
  PortalCatalogRole,
  PortalRequestCatalog,
} from "../../../lib/domain";
import { queryClient } from "../../../lib/query";
import { collectPermissionKeys, filterGroupsByApp } from "../permissionTree";

export type AccessGrantType = "permanent" | "timed";

interface CatalogView {
  apps: PortalCatalogApp[];
  roles: PortalCatalogRole[];
  permissionGroups: PermissionGroupItem[];
  ungroupedPermissions: PermissionItem[];
  visiblePermissionKeys: string[];
}

interface AccessRequestPayloadValues {
  appKey: string;
  roleKey: string;
  selectedPermissionKeys: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
}

interface AccessRequestFields extends AccessRequestPayloadValues {
  expandedGroupKeys: string[];
  setAppKey: Dispatch<SetStateAction<string>>;
  setRoleKey: Dispatch<SetStateAction<string>>;
  setSelectedPermissionKeys: Dispatch<SetStateAction<string[]>>;
  setExpandedGroupKeys: Dispatch<SetStateAction<string[]>>;
  setGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  setExpiresAt: Dispatch<SetStateAction<string>>;
  setReason: Dispatch<SetStateAction<string>>;
}

interface AccessRequestActions {
  changeAppKey: (nextAppKey: string) => void;
  togglePermission: (key: string) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

interface AccessRequestFormResult {
  appKey: string;
  roleKey: string;
  selectedPermissionKeys: string[];
  expandedGroupKeys: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
  apps: PortalCatalogApp[];
  roles: PortalCatalogRole[];
  permissionGroups: PermissionGroupItem[];
  ungroupedPermissions: PermissionItem[];
  visiblePermissionKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  submitErrorMessage: string;
  toastMessage: string;
  canSubmit: boolean;
  isSubmitting: boolean;
  changeAppKey: (nextAppKey: string) => void;
  changeRoleKey: Dispatch<SetStateAction<string>>;
  changeGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  changeExpiresAt: Dispatch<SetStateAction<string>>;
  changeReason: Dispatch<SetStateAction<string>>;
  togglePermission: (key: string) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

export function useAccessRequestForm(): AccessRequestFormResult {
  const fields = useAccessRequestFields();
  const catalogQuery = useQuery({
    queryKey: ["portal", "request-catalog"],
    queryFn: () => apiRequest<PortalRequestCatalog>("/portal/api/v1/request-catalog"),
  });
  const catalogView = useMemo(() => buildCatalogView(catalogQuery.data, fields.appKey), [fields.appKey, catalogQuery.data]);
  const submitMutation = useAccessRequestSubmitMutation(fields);
  const actions = buildAccessRequestActions(fields, () => submitMutation.mutate());
  const hasTarget = Boolean(fields.roleKey || fields.selectedPermissionKeys.length > 0);
  const canSubmit = Boolean(
    fields.appKey && hasTarget && fields.reason && (fields.grantType === "permanent" || fields.expiresAt) && !submitMutation.isPending,
  );

  return buildAccessRequestFormResult(fields, catalogView, catalogQuery.isLoading, catalogQuery.error, submitMutation, canSubmit, actions);
}

function useAccessRequestFields(): AccessRequestFields {
  const [appKey, setAppKey] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<string[]>([]);
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const [grantType, setGrantType] = useState<AccessGrantType>("permanent");
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");

  return {
    appKey,
    roleKey,
    selectedPermissionKeys,
    expandedGroupKeys,
    grantType,
    expiresAt,
    reason,
    setAppKey,
    setRoleKey,
    setSelectedPermissionKeys,
    setExpandedGroupKeys,
    setGrantType,
    setExpiresAt,
    setReason,
  };
}

function useAccessRequestSubmitMutation(fields: AccessRequestFields): UseMutationResult<unknown, Error, void, unknown> {
  return useMutation({
    mutationFn: () =>
      apiRequest("/portal/api/v1/me/access-requests", {
        method: "POST",
        body: buildAccessRequestPayload(fields),
      }),
    onSuccess: () => {
      fields.setRoleKey("");
      fields.setSelectedPermissionKeys([]);
      fields.setReason("");
      void queryClient.invalidateQueries({ queryKey: ["portal", "requests"] });
    },
  });
}

function buildAccessRequestFormResult(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  catalogIsLoading: boolean,
  catalogError: Error | null,
  submitMutation: UseMutationResult<unknown, Error, void, unknown>,
  canSubmit: boolean,
  actions: AccessRequestActions,
): AccessRequestFormResult {
  return {
    appKey: fields.appKey,
    roleKey: fields.roleKey,
    selectedPermissionKeys: fields.selectedPermissionKeys,
    expandedGroupKeys: fields.expandedGroupKeys,
    grantType: fields.grantType,
    expiresAt: fields.expiresAt,
    reason: fields.reason,
    apps: catalogView.apps,
    roles: catalogView.roles,
    permissionGroups: catalogView.permissionGroups,
    ungroupedPermissions: catalogView.ungroupedPermissions,
    visiblePermissionKeys: catalogView.visiblePermissionKeys,
    catalogIsLoading,
    catalogErrorMessage: catalogError ? catalogError.message : "",
    submitErrorMessage: submitMutation.error ? submitMutation.error.message : "",
    toastMessage: submitMutation.isSuccess ? "申请已提交" : "",
    canSubmit,
    isSubmitting: submitMutation.isPending,
    changeAppKey: actions.changeAppKey,
    changeRoleKey: fields.setRoleKey,
    changeGrantType: fields.setGrantType,
    changeExpiresAt: fields.setExpiresAt,
    changeReason: fields.setReason,
    togglePermission: actions.togglePermission,
    toggleGroup: actions.toggleGroup,
    submit: actions.submit,
  };
}

function buildAccessRequestActions(fields: AccessRequestFields, submit: () => void): AccessRequestActions {
  return {
    changeAppKey: (nextAppKey: string) => {
      fields.setAppKey(nextAppKey);
      fields.setRoleKey("");
      fields.setSelectedPermissionKeys([]);
      fields.setExpandedGroupKeys([]);
    },
    togglePermission: (key: string) => {
      fields.setSelectedPermissionKeys((current) => toggleListItem(current, key));
    },
    toggleGroup: (key: string) => {
      fields.setExpandedGroupKeys((current) => toggleListItem(current, key));
    },
    submit,
  };
}

function buildCatalogView(catalog: PortalRequestCatalog | undefined, appKey: string): CatalogView {
  const permissionGroups = filterGroupsByApp(catalog?.permission_groups ?? [], appKey);
  const ungroupedPermissions = (catalog?.ungrouped_permissions ?? []).filter(
    (permission) => !appKey || permission.app_key === appKey,
  );

  return {
    apps: catalog?.apps ?? [],
    roles: (catalog?.roles ?? []).filter((role) => !appKey || role.app_key === appKey),
    permissionGroups,
    ungroupedPermissions,
    visiblePermissionKeys: collectPermissionKeys(permissionGroups, ungroupedPermissions),
  };
}

function buildAccessRequestPayload(values: AccessRequestPayloadValues): JsonObject {
  return {
    app_key: values.appKey,
    request_type: "grant",
    role_keys: values.roleKey ? [values.roleKey] : [],
    permission_keys: values.selectedPermissionKeys,
    grant_type: values.grantType,
    grant_expires_at: values.grantType === "timed" && values.expiresAt ? new Date(values.expiresAt).toISOString() : null,
    reason: values.reason,
  };
}

function toggleListItem(items: string[], key: string): string[] {
  return items.includes(key) ? items.filter((item) => item !== key) : [...items, key];
}
