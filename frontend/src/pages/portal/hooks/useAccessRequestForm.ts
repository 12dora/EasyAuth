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
  default_approver_user_ids?: string[];
}

export interface ApproverOption {
  user_id: string;
  name?: string;
  label?: string;
  display_name?: string;
  email?: string;
  department?: string;
}

type PortalCatalogAppView = PortalCatalogApp & { default_approver_user_ids?: string[] };

export interface ScopeOption {
  key: string;
  name: string;
  description?: string;
}

export type ScopedPermissionItem = PermissionItem & { scopes?: ScopeOption[]; default_approver_user_ids?: string[] };
export type ScopedPermissionGroupItem = Omit<PermissionGroupItem, "children" | "permissions"> & {
  children?: Array<ScopedPermissionGroupItem | ScopedPermissionItem>;
  permissions?: ScopedPermissionItem[];
};

const directGrantSelectionSeparator = "::scope::";

interface PortalRequestCatalogView extends Omit<PortalRequestCatalog, "permission_groups" | "ungrouped_permissions"> {
  apps?: PortalCatalogAppView[];
  approver_options?: ApproverOption[];
  authorization_groups?: AuthorizationGroupItem[];
  permission_groups?: ScopedPermissionGroupItem[];
  ungrouped_permissions?: ScopedPermissionItem[];
}

interface CatalogView {
  apps: PortalCatalogAppView[];
  approverOptions: ApproverOption[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  visiblePermissionKeys: string[];
  scopesByPermissionKey: Record<string, ScopeOption[]>;
  permissionsByKey: Record<string, ScopedPermissionItem>;
}

interface AccessRequestPayloadValues {
  appKey: string;
  authorizationGroupKey: string;
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  selectedApproverUserIds: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
}

interface AccessRequestFields extends AccessRequestPayloadValues {
  expandedGroupKeys: string[];
  approverSelectionWasEdited: boolean;
  setAppKey: Dispatch<SetStateAction<string>>;
  setAuthorizationGroupKey: Dispatch<SetStateAction<string>>;
  setSelectedPermissionKeys: Dispatch<SetStateAction<string[]>>;
  setSelectedPermissionScopes: Dispatch<SetStateAction<Record<string, string>>>;
  setSelectedApproverUserIds: Dispatch<SetStateAction<string[]>>;
  setApproverSelectionWasEdited: Dispatch<SetStateAction<boolean>>;
  setExpandedGroupKeys: Dispatch<SetStateAction<string[]>>;
  setGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  setExpiresAt: Dispatch<SetStateAction<string>>;
  setReason: Dispatch<SetStateAction<string>>;
}

interface AccessRequestActions {
  changeAppKey: (nextAppKey: string) => void;
  changeAuthorizationGroupKey: (groupKey: string) => void;
  togglePermission: (key: string) => void;
  togglePermissionGroup: (group: ScopedPermissionGroupItem, shouldSelect: boolean) => void;
  toggleApprover: (userId: string) => void;
  changePermissionScope: (permissionKey: string, scopeKey: string) => void;
  changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

interface AccessRequestFormResult {
  appKey: string;
  authorizationGroupKey: string;
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  selectedApproverUserIds: string[];
  expandedGroupKeys: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
  apps: PortalCatalogAppView[];
  approverOptions: ApproverOption[];
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
  changeAuthorizationGroupKey: (groupKey: string) => void;
  changeGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  changeExpiresAt: Dispatch<SetStateAction<string>>;
  changeReason: Dispatch<SetStateAction<string>>;
  toggleApprover: (userId: string) => void;
  togglePermission: (key: string) => void;
  togglePermissionGroup: (group: ScopedPermissionGroupItem, shouldSelect: boolean) => void;
  changePermissionScope: (permissionKey: string, scopeKey: string) => void;
  changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string) => void;
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
  useDefaultApprovers(fields, catalogView);
  const submitMutation = useAccessRequestSubmitMutation(fields);
  const actions = buildAccessRequestActions(fields, () => submitMutation.mutate());
  const hasTarget = Boolean(fields.authorizationGroupKey || fields.selectedPermissionKeys.length > 0);
  const selectedScopesAreComplete = fields.selectedPermissionKeys.every((key) => hasSelectionScope(key, fields.selectedPermissionScopes));
  const canSubmit = Boolean(
    fields.appKey &&
      hasTarget &&
      selectedScopesAreComplete &&
      fields.selectedApproverUserIds.length > 0 &&
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
  const [selectedApproverUserIds, setSelectedApproverUserIds] = useState<string[]>([]);
  const [approverSelectionWasEdited, setApproverSelectionWasEdited] = useState(false);
  const [expandedGroupKeys, setExpandedGroupKeys] = useState<string[]>([]);
  const [grantType, setGrantType] = useState<AccessGrantType>("permanent");
  const [expiresAt, setExpiresAt] = useState("");
  const [reason, setReason] = useState("");

  return {
    appKey,
    authorizationGroupKey,
    selectedPermissionKeys,
    selectedPermissionScopes,
    selectedApproverUserIds,
    expandedGroupKeys,
    approverSelectionWasEdited,
    grantType,
    expiresAt,
    reason,
    setAppKey,
    setAuthorizationGroupKey,
    setSelectedPermissionKeys,
    setSelectedPermissionScopes,
    setSelectedApproverUserIds,
    setApproverSelectionWasEdited,
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
      fields.setApproverSelectionWasEdited(false);
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
    selectedApproverUserIds: fields.selectedApproverUserIds,
    expandedGroupKeys: fields.expandedGroupKeys,
    grantType: fields.grantType,
    expiresAt: fields.expiresAt,
    reason: fields.reason,
    apps: catalogView.apps,
    approverOptions: catalogView.approverOptions,
    authorizationGroups: catalogView.authorizationGroups,
    permissionGroups: catalogView.permissionGroups,
    ungroupedPermissions: catalogView.ungroupedPermissions,
    visiblePermissionKeys: catalogView.visiblePermissionKeys,
    catalogIsLoading,
    catalogErrorMessage: catalogError ? catalogError.message : "",
    submitErrorMessage: submitMutation.error ? submitMutation.error.message : "",
    toastMessage: submitMutation.isSuccess ? "申请已提交" : noDirectPermissionsToastMessage(fields, catalogView, catalogIsLoading),
    canSubmit,
    isSubmitting: submitMutation.isPending,
    changeAppKey: actions.changeAppKey,
    changeAuthorizationGroupKey: actions.changeAuthorizationGroupKey,
    changeGrantType: fields.setGrantType,
    changeExpiresAt: fields.setExpiresAt,
    changeReason: fields.setReason,
    toggleApprover: actions.toggleApprover,
    togglePermission: actions.togglePermission,
    togglePermissionGroup: actions.togglePermissionGroup,
    changePermissionScope: actions.changePermissionScope,
    changePermissionGroupScope: actions.changePermissionGroupScope,
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
      fields.setSelectedApproverUserIds([]);
      fields.setApproverSelectionWasEdited(false);
    },
    changeAuthorizationGroupKey: (groupKey: string) => {
      fields.setAuthorizationGroupKey(groupKey);
    },
    togglePermission: (key: string) => {
      fields.setSelectedPermissionKeys((current) => toggleListItem(current, key));
    },
    togglePermissionGroup: (group: ScopedPermissionGroupItem, shouldSelect: boolean) => {
      const groupSelectionKeys = collectPermissionGroupSelectionKeys(group);
      const groupSelectionKeySet = new Set(groupSelectionKeys);
      fields.setSelectedPermissionKeys((current) =>
        shouldSelect ? uniqueStrings([...current, ...groupSelectionKeys]) : current.filter((key) => !groupSelectionKeySet.has(key)),
      );
    },
    toggleApprover: (userId: string) => {
      fields.setApproverSelectionWasEdited(true);
      fields.setSelectedApproverUserIds((current) => toggleListItem(current, userId));
    },
    changePermissionScope: (permissionKey: string, scopeKey: string) => {
      fields.setSelectedPermissionScopes((current) => ({ ...current, [permissionKey]: scopeKey }));
    },
    changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string) => {
      if (!scopeKey) {
        return;
      }
      const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) =>
        (permission.scopes ?? []).some((scope) => scope.key === scopeKey),
      );
      const targetSelectionKeyByPermissionKey = new Map(
        supportedPermissions
          .filter((permission) => (permission.scopes ?? []).length > 1)
          .map((permission) => [permission.key, directGrantSelectionKey(permission.key, scopeKey)]),
      );

      fields.setSelectedPermissionKeys((current) => {
        const handledPermissionKeys = new Set<string>();
        const next: string[] = [];
        for (const selectionKey of current) {
          const permissionKey = directGrantSelectionPermissionKey(selectionKey);
          const targetSelectionKey = targetSelectionKeyByPermissionKey.get(permissionKey);
          if (targetSelectionKey) {
            if (!handledPermissionKeys.has(permissionKey)) {
              next.push(targetSelectionKey);
              handledPermissionKeys.add(permissionKey);
            }
            continue;
          }
          next.push(selectionKey);
        }
        for (const permission of supportedPermissions) {
          const scopes = permission.scopes ?? [];
          if (scopes.length > 1) {
            if (!handledPermissionKeys.has(permission.key)) {
              next.push(directGrantSelectionKey(permission.key, scopeKey));
              handledPermissionKeys.add(permission.key);
            }
            continue;
          }
          next.push(permission.key);
        }
        return uniqueStrings(next);
      });
      fields.setSelectedPermissionScopes((current) => {
        let changed = false;
        const next = { ...current };
        for (const permission of supportedPermissions) {
          const scopes = permission.scopes ?? [];
          if (scopes.length <= 1 && next[permission.key] !== scopeKey) {
            next[permission.key] = scopeKey;
            changed = true;
          }
        }
        return changed ? next : current;
      });
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
  const permissionsByKey = buildPermissionsByKey(permissionGroups, ungroupedPermissions);

  return {
    apps: catalog?.apps ?? [],
    approverOptions: catalog?.approver_options ?? [],
    authorizationGroups: (catalog?.authorization_groups ?? []).filter((group) => !appKey || group.app_key === appKey),
    permissionGroups,
    ungroupedPermissions,
    visiblePermissionKeys: collectPermissionKeys(permissionGroups, ungroupedPermissions),
    scopesByPermissionKey,
    permissionsByKey,
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
    approver_user_ids: values.selectedApproverUserIds,
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

function uniqueStrings(items: string[]): string[] {
  return Array.from(new Set(items.filter(Boolean)));
}

function collectPermissionGroupSelectionKeys(group: ScopedPermissionGroupItem): string[] {
  return collectScopedGroupPermissions(group).flatMap((permission) => permissionSelectionKeys(permission));
}

function permissionSelectionKeys(permission: ScopedPermissionItem): string[] {
  const scopes = permission.scopes ?? [];
  if (scopes.length > 1) {
    return scopes.map((scope) => directGrantSelectionKey(permission.key, scope.key));
  }
  return [permission.key];
}

function collectScopedGroupPermissions(group: ScopedPermissionGroupItem): ScopedPermissionItem[] {
  const childGroups = (group.children ?? []).filter(
    (child): child is ScopedPermissionGroupItem => "type" in child && child.type === "group",
  );
  return [...(group.permissions ?? []), ...childGroups.flatMap((childGroup) => collectScopedGroupPermissions(childGroup))];
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

function useDefaultApprovers(fields: AccessRequestFields, catalogView: CatalogView): void {
  const { appKey, authorizationGroupKey, selectedPermissionKeys, approverSelectionWasEdited, setSelectedApproverUserIds } = fields;
  const defaultApproverUserIds = useMemo(
    () => buildDefaultApproverUserIds(fields, catalogView),
    [catalogView, appKey, authorizationGroupKey, selectedPermissionKeys],
  );

  useEffect(() => {
    if (approverSelectionWasEdited) {
      return;
    }
    setSelectedApproverUserIds((current) =>
      listsAreEqual(current, defaultApproverUserIds) ? current : defaultApproverUserIds,
    );
  }, [approverSelectionWasEdited, defaultApproverUserIds, setSelectedApproverUserIds]);
}

function buildDefaultApproverUserIds(values: AccessRequestPayloadValues, catalogView: CatalogView): string[] {
  const app = catalogView.apps.find((item) => item.app_key === values.appKey);
  const authorizationGroup = catalogView.authorizationGroups.find((group) => group.key === values.authorizationGroupKey);
  const directGrantPermissionKeys = Array.from(
    new Set(values.selectedPermissionKeys.map((key) => directGrantSelectionPermissionKey(key))),
  );
  const directGrantApprovers = directGrantPermissionKeys.flatMap(
    (permissionKey) => catalogView.permissionsByKey[permissionKey]?.default_approver_user_ids ?? [],
  );
  const targetApprovers = uniqueUserIds([...(authorizationGroup?.default_approver_user_ids ?? []), ...directGrantApprovers]);
  if (targetApprovers.length > 0) {
    return targetApprovers;
  }
  return uniqueUserIds(app?.default_approver_user_ids ?? []);
}

function noDirectPermissionsToastMessage(fields: AccessRequestFields, catalogView: CatalogView, catalogIsLoading: boolean): string {
  if (catalogIsLoading || !fields.appKey || catalogView.visiblePermissionKeys.length > 0) {
    return "";
  }
  return "当前应用没有可直接申请的权限，可仅按权限组发起申请。";
}

function buildScopesByPermissionKey(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
): Record<string, ScopeOption[]> {
  const permissions = [...collectScopedPermissions(groups), ...ungroupedPermissions];
  return Object.fromEntries(permissions.map((permission) => [permission.key, permission.scopes ?? []]));
}

function buildPermissionsByKey(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
): Record<string, ScopedPermissionItem> {
  const permissions = [...collectScopedPermissions(groups), ...ungroupedPermissions];
  return Object.fromEntries(permissions.map((permission) => [permission.key, permission]));
}

function collectScopedPermissions(groups: ScopedPermissionGroupItem[]): ScopedPermissionItem[] {
  return groups.flatMap((group) => {
    const childGroups = (group.children ?? []).filter(
      (child): child is ScopedPermissionGroupItem => "type" in child && child.type === "group",
    );
    const childPermissions = (group.children ?? []).filter(
      (child): child is ScopedPermissionItem => !("type" in child) || child.type !== "group",
    );
    return [...(group.permissions ?? []), ...childPermissions, ...collectScopedPermissions(childGroups)];
  });
}

function uniqueUserIds(userIds: string[]): string[] {
  return Array.from(new Set(userIds.filter(Boolean)));
}

function listsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}
