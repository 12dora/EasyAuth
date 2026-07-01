import { useMutation, useQuery } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type {
  PermissionGroupItem,
  PermissionItem,
  PortalCatalogApp,
  PortalRequestCatalog,
} from "../../../lib/domain";
import { queryClient } from "../../../lib/query";
import { collectPermissionKeys, filterGroupsByApp } from "../permissionTree";

export type AccessGrantType = "permanent" | "timed";

export interface AuthorizationGroupItem {
  id: number;
  app_key: string;
  key: string;
  kind: "role" | "bundle" | string;
  name: string;
  description?: string;
  requestable?: boolean;
  requires_approval?: boolean;
}

export interface ScopeOption {
  key: string;
  name: string;
  description?: string;
}

export type ScopedPermissionItem = PermissionItem & { scopes?: ScopeOption[] };
export type ScopedPermissionGroupItem = Omit<PermissionGroupItem, "children" | "permissions"> & {
  children?: Array<ScopedPermissionGroupItem | ScopedPermissionItem>;
  permissions?: ScopedPermissionItem[];
};

const directGrantSelectionSeparator = "::scope::";

interface PortalRequestCatalogView extends Omit<PortalRequestCatalog, "permission_groups" | "ungrouped_permissions"> {
  authorization_groups?: AuthorizationGroupItem[];
  permission_groups?: ScopedPermissionGroupItem[];
  ungrouped_permissions?: ScopedPermissionItem[];
}

interface CatalogView {
  apps: PortalCatalogApp[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  visiblePermissionKeys: string[];
  scopesByPermissionKey: Record<string, ScopeOption[]>;
}

interface AccessRequestPayloadValues {
  appKey: string;
  authorizationGroupKey: string;
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
}

interface AccessRequestFields extends AccessRequestPayloadValues {
  expandedGroupKeys: string[];
  setAppKey: Dispatch<SetStateAction<string>>;
  setAuthorizationGroupKey: Dispatch<SetStateAction<string>>;
  setSelectedPermissionKeys: Dispatch<SetStateAction<string[]>>;
  setSelectedPermissionScopes: Dispatch<SetStateAction<Record<string, string>>>;
  setExpandedGroupKeys: Dispatch<SetStateAction<string[]>>;
  setGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  setExpiresAt: Dispatch<SetStateAction<string>>;
  setReason: Dispatch<SetStateAction<string>>;
}

interface AccessRequestActions {
  changeAppKey: (nextAppKey: string) => void;
  togglePermission: (key: string) => void;
  changePermissionScope: (permissionKey: string, scopeKey: string) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

interface AccessRequestFormResult {
  appKey: string;
  authorizationGroupKey: string;
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  expandedGroupKeys: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
  apps: PortalCatalogApp[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  visiblePermissionKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  submitErrorMessage: string;
  toastMessage: string;
  canSubmit: boolean;
  isSubmitting: boolean;
  changeAppKey: (nextAppKey: string) => void;
  changeAuthorizationGroupKey: Dispatch<SetStateAction<string>>;
  changeGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  changeExpiresAt: Dispatch<SetStateAction<string>>;
  changeReason: Dispatch<SetStateAction<string>>;
  togglePermission: (key: string) => void;
  changePermissionScope: (permissionKey: string, scopeKey: string) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

export function useAccessRequestForm(): AccessRequestFormResult {
  const fields = useAccessRequestFields();
  const catalogQuery = useQuery({
    queryKey: ["portal", "request-catalog"],
    queryFn: () => apiRequest<PortalRequestCatalogView>("/portal/api/v1/request-catalog"),
  });
  const catalogView = useMemo(() => buildCatalogView(catalogQuery.data, fields.appKey), [fields.appKey, catalogQuery.data]);
  useDefaultSingleScopes(fields.setSelectedPermissionScopes, catalogView);
  const submitMutation = useAccessRequestSubmitMutation(fields);
  const actions = buildAccessRequestActions(fields, () => submitMutation.mutate());
  const hasTarget = Boolean(fields.authorizationGroupKey || fields.selectedPermissionKeys.length > 0);
  const selectedScopesAreComplete = fields.selectedPermissionKeys.every((key) => hasSelectionScope(key, fields.selectedPermissionScopes));
  const canSubmit = Boolean(
    fields.appKey &&
      hasTarget &&
      selectedScopesAreComplete &&
      fields.reason &&
      (fields.grantType === "permanent" || fields.expiresAt) &&
      !submitMutation.isPending,
  );

  return buildAccessRequestFormResult(fields, catalogView, catalogQuery.isLoading, catalogQuery.error, submitMutation, canSubmit, actions);
}

function useAccessRequestFields(): AccessRequestFields {
  const [appKey, setAppKey] = useState("");
  const [authorizationGroupKey, setAuthorizationGroupKey] = useState("");
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<string[]>([]);
  const [selectedPermissionScopes, setSelectedPermissionScopes] = useState<Record<string, string>>({});
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const [grantType, setGrantType] = useState<AccessGrantType>("permanent");
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");

  return {
    appKey,
    authorizationGroupKey,
    selectedPermissionKeys,
    selectedPermissionScopes,
    expandedGroupKeys,
    grantType,
    expiresAt,
    reason,
    setAppKey,
    setAuthorizationGroupKey,
    setSelectedPermissionKeys,
    setSelectedPermissionScopes,
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
      fields.setAuthorizationGroupKey("");
      fields.setSelectedPermissionKeys([]);
      fields.setSelectedPermissionScopes({});
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
    authorizationGroupKey: fields.authorizationGroupKey,
    selectedPermissionKeys: fields.selectedPermissionKeys,
    selectedPermissionScopes: fields.selectedPermissionScopes,
    expandedGroupKeys: fields.expandedGroupKeys,
    grantType: fields.grantType,
    expiresAt: fields.expiresAt,
    reason: fields.reason,
    apps: catalogView.apps,
    authorizationGroups: catalogView.authorizationGroups,
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
    changeAuthorizationGroupKey: fields.setAuthorizationGroupKey,
    changeGrantType: fields.setGrantType,
    changeExpiresAt: fields.setExpiresAt,
    changeReason: fields.setReason,
    togglePermission: actions.togglePermission,
    changePermissionScope: actions.changePermissionScope,
    toggleGroup: actions.toggleGroup,
    submit: actions.submit,
  };
}

function buildAccessRequestActions(fields: AccessRequestFields, submit: () => void): AccessRequestActions {
  return {
    changeAppKey: (nextAppKey: string) => {
      fields.setAppKey(nextAppKey);
      fields.setAuthorizationGroupKey("");
      fields.setSelectedPermissionKeys([]);
      fields.setSelectedPermissionScopes({});
      fields.setExpandedGroupKeys([]);
    },
    togglePermission: (key: string) => {
      fields.setSelectedPermissionKeys((current) => toggleListItem(current, key));
    },
    changePermissionScope: (permissionKey: string, scopeKey: string) => {
      fields.setSelectedPermissionScopes((current) => ({ ...current, [permissionKey]: scopeKey }));
    },
    toggleGroup: (key: string) => {
      fields.setExpandedGroupKeys((current) => toggleListItem(current, key));
    },
    submit,
  };
}

function buildCatalogView(catalog: PortalRequestCatalogView | undefined, appKey: string): CatalogView {
  const permissionGroups = filterGroupsByApp(catalog?.permission_groups ?? [], appKey);
  const ungroupedPermissions = (catalog?.ungrouped_permissions ?? []).filter(
    (permission) => !appKey || permission.app_key === appKey,
  );
  const scopesByPermissionKey = buildScopesByPermissionKey(permissionGroups, ungroupedPermissions);

  return {
    apps: catalog?.apps ?? [],
    authorizationGroups: (catalog?.authorization_groups ?? []).filter((group) => !appKey || group.app_key === appKey),
    permissionGroups,
    ungroupedPermissions,
    visiblePermissionKeys: collectPermissionKeys(permissionGroups, ungroupedPermissions),
    scopesByPermissionKey,
  };
}

function buildAccessRequestPayload(values: AccessRequestPayloadValues): JsonObject {
  return {
    app_key: values.appKey,
    request_type: "grant",
    authorization_group_keys: values.authorizationGroupKey ? [values.authorizationGroupKey] : [],
    direct_grants: values.selectedPermissionKeys.map((permissionKey) => ({
      permission: directGrantSelectionPermissionKey(permissionKey),
      scope: directGrantSelectionScopeKey(permissionKey) ?? values.selectedPermissionScopes[permissionKey],
    })),
    grant_type: values.grantType,
    grant_expires_at: values.grantType === "timed" && values.expiresAt ? new Date(values.expiresAt).toISOString() : null,
    reason: values.reason,
  };
}

export function directGrantSelectionKey(permissionKey: string, scopeKey: string): string {
  return `${permissionKey}${directGrantSelectionSeparator}${scopeKey}`;
}

export function directGrantSelectionPermissionKey(selectionKey: string): string {
  return selectionKey.includes(directGrantSelectionSeparator) ? selectionKey.split(directGrantSelectionSeparator, 1)[0] : selectionKey;
}

export function directGrantSelectionScopeKey(selectionKey: string): string | null {
  const separatorIndex = selectionKey.indexOf(directGrantSelectionSeparator);
  return separatorIndex === -1 ? null : selectionKey.slice(separatorIndex + directGrantSelectionSeparator.length);
}

function hasSelectionScope(selectionKey: string, selectedScopes: Record<string, string>): boolean {
  return Boolean(directGrantSelectionScopeKey(selectionKey) ?? selectedScopes[selectionKey]);
}

function toggleListItem(items: string[], key: string): string[] {
  return items.includes(key) ? items.filter((item) => item !== key) : [...items, key];
}

function useDefaultSingleScopes(
  setSelectedPermissionScopes: Dispatch<SetStateAction<Record<string, string>>>,
  catalogView: CatalogView,
): void {
  useEffect(() => {
    setSelectedPermissionScopes((current) => {
      const next: Record<string, string> = {};
      let changed = false;
      for (const permissionKey of catalogView.visiblePermissionKeys) {
        const scopes = catalogView.scopesByPermissionKey[permissionKey] ?? [];
        const currentScope = current[permissionKey];
        if (currentScope && scopes.some((scope) => scope.key === currentScope)) {
          next[permissionKey] = currentScope;
          continue;
        }
        if (scopes.length === 1) {
          next[permissionKey] = scopes[0].key;
          changed = true;
        } else if (currentScope) {
          changed = true;
        }
      }
      return changed || Object.keys(current).length !== Object.keys(next).length ? next : current;
    });
  }, [catalogView.scopesByPermissionKey, catalogView.visiblePermissionKeys, setSelectedPermissionScopes]);
}

function buildScopesByPermissionKey(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
): Record<string, ScopeOption[]> {
  const permissions = [...collectScopedPermissions(groups), ...ungroupedPermissions];
  return Object.fromEntries(permissions.map((permission) => [permission.key, permission.scopes ?? []]));
}

function collectScopedPermissions(groups: ScopedPermissionGroupItem[]): ScopedPermissionItem[] {
  return groups.flatMap((group) => {
    const childGroups = (group.children ?? []).filter(
      (child): child is ScopedPermissionGroupItem => "type" in child && child.type === "group",
    );
    return [...(group.permissions ?? []), ...collectScopedPermissions(childGroups)];
  });
}
