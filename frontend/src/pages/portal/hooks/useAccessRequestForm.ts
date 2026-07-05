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
import { collectPermissionKeys, filterGroupsByApp, permissionMatchesApp } from "../permissionTree";

export type AccessGrantType = "permanent" | "timed";

export interface AuthorizationGroupItem {
  id: number;
  app_key: string;
  key: string;
  kind: "role" | "bundle" | string;
  name: string;
  name_en?: string;
  description?: string;
  description_en?: string;
  requestable?: boolean;
  requires_approval?: boolean;
  default_approver_user_ids?: string[];
  approver_resolution_status?: string;
  scopes?: ScopeOption[];
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
  name_en?: string;
  description?: string;
  description_en?: string;
}

export type ScopedPermissionItem = PermissionItem & {
  scopes?: ScopeOption[];
  default_approver_user_ids?: string[];
  approver_resolution_status?: string;
};
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
  selectPermissionKeys: (keys: string[]) => void;
  clearPermissionKeys: (keys: string[]) => void;
  expandGroups: (keys: string[]) => void;
  collapseGroups: (keys: string[]) => void;
  toggleApprover: (userId: string) => void;
  changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => void;
  changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
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
  expiresAtError: boolean;
  isSubmitting: boolean;
  changeAppKey: (nextAppKey: string) => void;
  changeAuthorizationGroupKey: (groupKey: string) => void;
  changeGrantType: Dispatch<SetStateAction<AccessGrantType>>;
  changeExpiresAt: Dispatch<SetStateAction<string>>;
  changeReason: Dispatch<SetStateAction<string>>;
  selectPermissionKeys: (keys: string[]) => void;
  clearPermissionKeys: (keys: string[]) => void;
  expandGroups: (keys: string[]) => void;
  collapseGroups: (keys: string[]) => void;
  toggleApprover: (userId: string) => void;
  changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => void;
  changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  toggleGroup: (key: string) => void;
  submit: () => void;
}

export function useAccessRequestForm(currentUserId = ""): AccessRequestFormResult {
  const fields = useAccessRequestFields();
  const catalogQuery = useQuery({
    queryKey: ["portal", "request-catalog"],
    queryFn: () => apiRequest<PortalRequestCatalogView>("/portal/api/v1/request-catalog"),
  });
  const catalogView = useMemo(
    () => buildCatalogView(catalogQuery.data, fields.appKey, currentUserId),
    [fields.appKey, catalogQuery.data, currentUserId],
  );
  useDefaultSingleScopes(fields.setSelectedPermissionScopes, catalogView);
  useDefaultApprovers(fields, catalogView, currentUserId);
  const submitMutation = useAccessRequestSubmitMutation(fields);
  const actions = buildAccessRequestActions(fields, catalogView, () => submitMutation.mutate());
  const hasTarget = Boolean(fields.authorizationGroupKey || fields.selectedPermissionKeys.length > 0);
  const selectedScopesAreComplete = fields.selectedPermissionKeys.every((key) => hasSelectionScope(key));
  // 限时授权必须选择"未来"的过期时间, 否则后端会视为已过期而白跑一次审批。
  const expiresAtIsFuture = Boolean(fields.expiresAt) && new Date(fields.expiresAt) > new Date();
  const expiresAtError = fields.grantType === "timed" && Boolean(fields.expiresAt) && !expiresAtIsFuture;
  const canSubmit = Boolean(
    fields.appKey &&
      hasTarget &&
      selectedScopesAreComplete &&
      fields.selectedApproverUserIds.length > 0 &&
      !fields.selectedApproverUserIds.includes(currentUserId) &&
      fields.reason.trim().length > 0 &&
      (fields.grantType === "permanent" || expiresAtIsFuture) &&
      !submitMutation.isPending,
  );

  return buildAccessRequestFormResult(fields, catalogView, catalogQuery.isLoading, catalogQuery.error, submitMutation, canSubmit, expiresAtError, actions);
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
  expiresAtError: boolean,
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
    toastMessage: submitMutation.isSuccess ? "申请已提交" : accessRequestToastMessage(fields, catalogView, catalogIsLoading),
    canSubmit,
    expiresAtError,
    isSubmitting: submitMutation.isPending,
    changeAppKey: actions.changeAppKey,
    changeAuthorizationGroupKey: actions.changeAuthorizationGroupKey,
    changeGrantType: fields.setGrantType,
    changeExpiresAt: fields.setExpiresAt,
    changeReason: fields.setReason,
    selectPermissionKeys: actions.selectPermissionKeys,
    clearPermissionKeys: actions.clearPermissionKeys,
    expandGroups: actions.expandGroups,
    collapseGroups: actions.collapseGroups,
    toggleApprover: actions.toggleApprover,
    changePermissionScope: actions.changePermissionScope,
    changePermissionGroupScope: actions.changePermissionGroupScope,
    toggleGroup: actions.toggleGroup,
    submit: actions.submit,
  };
}

function buildAccessRequestActions(fields: AccessRequestFields, catalogView: CatalogView, submit: () => void): AccessRequestActions {
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
    selectPermissionKeys: (keys: string[]) => {
      fields.setSelectedPermissionKeys((current) => uniqueStrings([...current, ...keys]));
    },
    clearPermissionKeys: (keys: string[]) => {
      const keySet = new Set(keys);
      fields.setSelectedPermissionKeys((current) => current.filter((key) => !keySet.has(key)));
    },
    expandGroups: (keys: string[]) => {
      fields.setExpandedGroupKeys((current) => uniqueStrings([...current, ...keys]));
    },
    collapseGroups: (keys: string[]) => {
      const keySet = new Set(keys.flatMap((key) => [key, ...descendantGroupKeys(catalogView.permissionGroups, key)]));
      fields.setExpandedGroupKeys((current) => current.filter((key) => !keySet.has(key)));
    },
    toggleApprover: (userId: string) => {
      fields.setApproverSelectionWasEdited(true);
      fields.setSelectedApproverUserIds((current) => toggleListItem(current, userId));
    },
    changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => {
      fields.setSelectedPermissionKeys((current) => {
        const shouldSelect = !selectedScopeKeysForPermission(permission, current).includes(scopeKey);
        return nextPermissionScopeSelection(permission, scopeKey, shouldSelect, current);
      });
    },
    changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => {
      if (!scopeKey) {
        return;
      }
      const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) => permissionScopeSelectionKey(permission, scopeKey));

      fields.setSelectedPermissionKeys((current) => {
        let next = current;
        for (const permission of supportedPermissions) {
          next = shouldSelect
            ? nextPermissionScopeSelection(permission, scopeKey, true, next)
            : nextPermissionScopeCascadeClearSelection(permission, scopeKey, next);
        }
        return next;
      });
    },
    toggleGroup: (key: string) => {
      fields.setExpandedGroupKeys((current) => {
        if (!current.includes(key)) {
          return [...current, key];
        }
        const keySet = new Set([key, ...descendantGroupKeys(catalogView.permissionGroups, key)]);
        return current.filter((item) => !keySet.has(item));
      });
    },
    submit,
  };
}

function buildCatalogView(catalog: PortalRequestCatalogView | undefined, appKey: string, currentUserId: string): CatalogView {
  const permissionGroups = filterGroupsByApp(catalog?.permission_groups ?? [], appKey);
  // FF-12: 未分组权限沿用与分组一致的应用作用域判定, 保持应用无关权限在两条路径下同样可见。
  const ungroupedPermissions = (catalog?.ungrouped_permissions ?? []).filter((permission) =>
    permissionMatchesApp(permission, appKey),
  );
  const scopesByPermissionKey = buildScopesByPermissionKey(permissionGroups, ungroupedPermissions);
  const permissionsByKey = buildPermissionsByKey(permissionGroups, ungroupedPermissions);

  return {
    apps: catalog?.apps ?? [],
    // FF-7: 申请人不得自选为审批人; 前端从候选中剔除自己(服务端仍是权威校验)。
    approverOptions: (catalog?.approver_options ?? []).filter((option) => option.user_id !== currentUserId),
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
    direct_grants: values.selectedPermissionKeys.map((selectionKey) => buildDirectGrantPayload(selectionKey)),
    approver_user_ids: values.selectedApproverUserIds,
    grant_type: values.grantType,
    grant_expires_at: values.grantType === "timed" && values.expiresAt ? new Date(values.expiresAt).toISOString() : null,
    reason: values.reason.trim(),
  };
}

function buildDirectGrantPayload(selectionKey: string): JsonObject {
  const scopeKey = directGrantSelectionScopeKey(selectionKey);
  if (!scopeKey) {
    throw new Error(`直接权限选择缺少权限范围: ${selectionKey}`);
  }
  return {
    permission: directGrantSelectionPermissionKey(selectionKey),
    scope: scopeKey,
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

function hasSelectionScope(selectionKey: string): boolean {
  return Boolean(directGrantSelectionScopeKey(selectionKey));
}

function toggleListItem(items: string[], key: string): string[] {
  return items.includes(key) ? items.filter((item) => item !== key) : [...items, key];
}

function uniqueStrings(items: string[]): string[] {
  return Array.from(new Set(items.filter(Boolean)));
}

export function permissionSelectionKeys(permission: ScopedPermissionItem): string[] {
  return permissionScopeKeys(permission).map((scopeKey) => directGrantSelectionKey(permission.key, scopeKey));
}

export function permissionScopeSelectionKey(permission: ScopedPermissionItem, scopeKey: string): string | null {
  return (permission.scopes ?? []).some((scope) => scope.key === scopeKey)
    ? directGrantSelectionKey(permission.key, scopeKey)
    : null;
}

export function permissionScopeKeys(permission: ScopedPermissionItem): string[] {
  const scopes = permission.scopes ?? [];
  return scopes.map((scope) => scope.key);
}

export function selectedScopeKeysForPermission(permission: ScopedPermissionItem, selectedPermissionKeys: string[]): string[] {
  const selectedKeySet = new Set(selectedPermissionKeys);
  return (permission.scopes ?? [])
    .filter((scope) => selectedKeySet.has(directGrantSelectionKey(permission.key, scope.key)))
    .map((scope) => scope.key);
}

export function nextPermissionScopeSelection(
  permission: ScopedPermissionItem,
  scopeKey: string,
  shouldSelect: boolean,
  selectedPermissionKeys: string[],
): string[] {
  const scopes = permission.scopes ?? [];
  const targetScopeIndex = scopes.findIndex((scope) => scope.key === scopeKey);
  if (targetScopeIndex === -1) {
    return selectedPermissionKeys;
  }
  const currentScopeKeys = selectedScopeKeysForPermission(permission, selectedPermissionKeys);
  const nextScopeKeys = shouldSelect
    ? scopes.slice(0, targetScopeIndex + 1).map((scope) => scope.key)
    : currentScopeKeys.filter((currentScopeKey) => {
        const currentScopeIndex = scopes.findIndex((scope) => scope.key === currentScopeKey);
        return currentScopeIndex !== -1 && currentScopeIndex < targetScopeIndex;
      });
  const permissionScopeKeySet = new Set(permissionSelectionKeys(permission));
  const otherSelectionKeys = selectedPermissionKeys.filter((selectionKey) => !permissionScopeKeySet.has(selectionKey));
  const nextPermissionSelectionKeys = nextScopeKeys
    .map((nextScopeKey) => permissionScopeSelectionKey(permission, nextScopeKey))
    .filter((selectionKey): selectionKey is string => Boolean(selectionKey));
  return uniqueStrings([...otherSelectionKeys, ...nextPermissionSelectionKeys]);
}

function nextPermissionScopeCascadeClearSelection(
  permission: ScopedPermissionItem,
  scopeKey: string,
  selectedPermissionKeys: string[],
): string[] {
  const scopes = permission.scopes ?? [];
  const targetScopeIndex = scopes.findIndex((scope) => scope.key === scopeKey);
  if (targetScopeIndex === -1) {
    return selectedPermissionKeys;
  }
  const removableScopeKeys = new Set(scopes.slice(0, targetScopeIndex + 1).map((scope) => scope.key));
  const removableSelectionKeys = new Set(
    permissionSelectionKeys(permission).filter((selectionKey) => {
      const selectedScopeKey = directGrantSelectionScopeKey(selectionKey);
      return selectedScopeKey !== null && removableScopeKeys.has(selectedScopeKey);
    }),
  );
  return selectedPermissionKeys.filter((selectionKey) => !removableSelectionKeys.has(selectionKey));
}

function collectScopedGroupPermissions(group: ScopedPermissionGroupItem, visited: Set<string> = new Set()): ScopedPermissionItem[] {
  // 环形分组图防御: 已访问过的分组短路, 避免无限递归。
  if (visited.has(group.key)) {
    return [];
  }
  visited.add(group.key);
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const permission of directPermissionsForGroup(group)) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const childGroup of childGroupsForGroup(group)) {
    for (const permission of collectScopedGroupPermissions(childGroup, visited)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values());
}

function descendantGroupKeys(groups: ScopedPermissionGroupItem[], groupKey: string): string[] {
  const group = findPermissionGroup(groups, groupKey);
  return group ? collectDescendantGroupKeys(group) : [];
}

function findPermissionGroup(
  groups: ScopedPermissionGroupItem[],
  groupKey: string,
  visited: Set<string> = new Set(),
): ScopedPermissionGroupItem | null {
  for (const group of groups) {
    if (group.key === groupKey) {
      return group;
    }
    // 环形分组图防御: 不重复进入已访问分组。
    if (visited.has(group.key)) {
      continue;
    }
    visited.add(group.key);
    const childResult = findPermissionGroup(childGroupsForGroup(group), groupKey, visited);
    if (childResult) {
      return childResult;
    }
  }
  return null;
}

function collectDescendantGroupKeys(group: ScopedPermissionGroupItem, visited: Set<string> = new Set()): string[] {
  // 环形分组图防御: 已访问过的分组短路, 避免无限递归。
  if (visited.has(group.key)) {
    return [];
  }
  visited.add(group.key);
  const childGroups = childGroupsForGroup(group);
  return childGroups.flatMap((childGroup) => [childGroup.key, ...collectDescendantGroupKeys(childGroup, visited)]);
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

function useDefaultApprovers(fields: AccessRequestFields, catalogView: CatalogView, currentUserId: string): void {
  const { appKey, authorizationGroupKey, selectedPermissionKeys, approverSelectionWasEdited, setSelectedApproverUserIds } = fields;
  const defaultApproverUserIds = useMemo(
    () => buildDefaultApproverUserIds(fields, catalogView, currentUserId),
    [catalogView, appKey, authorizationGroupKey, selectedPermissionKeys, currentUserId],
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

function buildDefaultApproverUserIds(values: AccessRequestPayloadValues, catalogView: CatalogView, currentUserId: string): string[] {
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
    // FF-7: 默认审批人同样剔除申请人自己。
    return targetApprovers.filter((userId) => userId !== currentUserId);
  }
  if (selectedManagedUsersTargetHasMissingDirectManager(values, catalogView)) {
    return [];
  }
  return uniqueUserIds(app?.default_approver_user_ids ?? []).filter((userId) => userId !== currentUserId);
}

function accessRequestToastMessage(fields: AccessRequestFields, catalogView: CatalogView, catalogIsLoading: boolean): string {
  if (selectedManagedUsersTargetHasMissingDirectManager(fields, catalogView)) {
    return "未找到直属上级，请补全审批人";
  }
  return noDirectPermissionsToastMessage(fields, catalogView, catalogIsLoading);
}

function noDirectPermissionsToastMessage(fields: AccessRequestFields, catalogView: CatalogView, catalogIsLoading: boolean): string {
  if (catalogIsLoading || !fields.appKey || catalogView.visiblePermissionKeys.length > 0) {
    return "";
  }
  return "当前应用没有可直接申请的权限，可仅按权限组发起申请。";
}

function selectedManagedUsersTargetHasMissingDirectManager(values: AccessRequestPayloadValues, catalogView: CatalogView): boolean {
  return selectedManagedUsersTargets(values, catalogView).some(
    (target) => target.approver_resolution_status === "direct_manager_missing",
  );
}

function selectedManagedUsersTargets(
  values: AccessRequestPayloadValues,
  catalogView: CatalogView,
): Array<AuthorizationGroupItem | ScopedPermissionItem> {
  const targets: Array<AuthorizationGroupItem | ScopedPermissionItem> = [];
  const authorizationGroup = catalogView.authorizationGroups.find((group) => group.key === values.authorizationGroupKey);
  if (authorizationGroup && targetHasManagedUsersScope(authorizationGroup)) {
    targets.push(authorizationGroup);
  }
  const directGrantPermissionKeys = Array.from(
    new Set(values.selectedPermissionKeys.map((key) => directGrantSelectionPermissionKey(key))),
  );
  for (const permissionKey of directGrantPermissionKeys) {
    const permission = catalogView.permissionsByKey[permissionKey];
    if (permission && targetHasManagedUsersScope(permission)) {
      targets.push(permission);
    }
  }
  return targets;
}

function targetHasManagedUsersScope(target: AuthorizationGroupItem | ScopedPermissionItem): boolean {
  return (target.scopes ?? []).some((scope) => scope.key === "MANAGED_USERS");
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
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const group of groups) {
    for (const permission of collectScopedGroupPermissions(group)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values());
}

function childGroupsForGroup(group: ScopedPermissionGroupItem): ScopedPermissionGroupItem[] {
  return (group.children ?? []).filter(
    (child): child is ScopedPermissionGroupItem => "type" in child && child.type === "group",
  );
}

function directPermissionsForGroup(group: ScopedPermissionGroupItem): ScopedPermissionItem[] {
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const permission of group.permissions ?? []) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const child of group.children ?? []) {
    if (!("type" in child) || child.type !== "group") {
      permissionsByKey.set(child.key, child);
    }
  }
  return Array.from(permissionsByKey.values());
}

function uniqueUserIds(userIds: string[]): string[] {
  return Array.from(new Set(userIds.filter(Boolean)));
}

function listsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}
