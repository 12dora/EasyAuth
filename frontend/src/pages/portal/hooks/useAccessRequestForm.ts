import { useMutation, useQuery } from "@tanstack/react-query";
import type { UseMutationResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { MessageKey } from "../../../i18n/messages";
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
import { parsePortalGrantList, type PortalGrantRow } from "../portalListPayload";
import { parsePortalRequestCatalog } from "../requestCatalogContract";

export type AccessGrantType = "permanent" | "timed";
export type AccessRequestType = "grant" | "change" | "revoke" | "renew";

export interface AuthorizationGroupGrantRef {
  permission_key: string;
  scope_key: string;
}

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
  grants?: AuthorizationGroupGrantRef[];
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

export const ACCESS_REQUEST_MAX_APPROVERS = 20;
export const ACCESS_REQUEST_MAX_REASON_LENGTH = 1000;

export interface PortalRequestCatalogView extends Omit<PortalRequestCatalog, "permission_groups" | "ungrouped_permissions"> {
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
  requestType: AccessRequestType;
  appKey: string;
  baseGrantId: string;
  baseGrantRevision: number | null;
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
  setRequestType: Dispatch<SetStateAction<AccessRequestType>>;
  setAppKey: Dispatch<SetStateAction<string>>;
  setBaseGrantId: Dispatch<SetStateAction<string>>;
  setBaseGrantRevision: Dispatch<SetStateAction<number | null>>;
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
  changeRequestType: (requestType: AccessRequestType) => void;
  changeBaseGrantId: (grantId: string) => void;
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
  requestType: AccessRequestType;
  appKey: string;
  baseGrantId: string;
  authorizationGroupKey: string;
  selectedPermissionKeys: string[];
  selectedPermissionScopes: Record<string, string>;
  selectedApproverUserIds: string[];
  expandedGroupKeys: string[];
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
  apps: PortalCatalogAppView[];
  currentGrants: PortalGrantRow[];
  approverOptions: ApproverOption[];
  authorizationGroups: AuthorizationGroupItem[];
  permissionGroups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  visiblePermissionKeys: string[];
  /** 所选权限组覆盖的权限范围(展示态联动勾选用, 不计入直接权限提交)。 */
  groupCoveredSelectionKeys: string[];
  catalogIsLoading: boolean;
  catalogErrorMessage: string;
  submitErrorMessage: string;
  /** 提示条文案的 i18n key: 由组件用 t() 渲染, hook 不生产用户可见文案。 */
  toastMessageKey: MessageKey | "";
  canSubmit: boolean;
  expiresAtError: boolean;
  isSubmitting: boolean;
  changeAppKey: (nextAppKey: string) => void;
  changeRequestType: (requestType: AccessRequestType) => void;
  changeBaseGrantId: (grantId: string) => void;
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
    queryFn: async () => parsePortalRequestCatalog(await apiRequest<unknown>("/portal/api/v1/request-catalog")),
  });
  const currentGrantsQuery = useQuery({
    queryKey: ["portal", "current-grants-selector"],
    queryFn: async () =>
      parsePortalGrantList(await apiRequest<unknown>("/portal/api/v1/me/grants?page=1&page_size=100")),
    enabled: fields.requestType !== "grant",
  });
  const catalogView = useMemo(
    () => buildCatalogView(catalogQuery.data, fields.appKey, currentUserId),
    [fields.appKey, catalogQuery.data, currentUserId],
  );
  useDefaultSingleScopes(fields.setSelectedPermissionScopes, catalogView);
  useGroupCoverageInvariant(fields, catalogView);
  useDefaultApprovers(fields, catalogView, currentUserId);
  const submitMutation = useAccessRequestSubmitMutation(fields, catalogView);
  const currentGrants = currentGrantsQuery.data?.data ?? [];
  const selectedBaseGrant = currentGrants.find((grant) => String(grant.grant_id) === fields.baseGrantId);
  useLifecycleGrantInvariant(fields, selectedBaseGrant);
  const actions = buildAccessRequestActions(fields, catalogView, currentGrants, () => submitMutation.mutate());
  const lifecycleSelectorActive = fields.requestType !== "grant";
  const hasTarget = fields.requestType === "revoke" || Boolean(fields.authorizationGroupKey || fields.selectedPermissionKeys.length > 0);
  const lifecycleHasBaseGrant = fields.requestType === "grant" || Boolean(selectedBaseGrant);
  const lifecycleSelectorIsComplete = fields.requestType !== "renew" || selectedBaseGrant?.grant_type === "timed";
  const currentGrantsTruncated = Boolean(currentGrantsQuery.data && currentGrantsQuery.data.pagination.total_pages > 1);
  const selectedScopesAreComplete = fields.selectedPermissionKeys.every((key) => hasSelectionScope(key));
  const managedUsersTargetHasMissingDirectManager = selectedManagedUsersTargetHasMissingDirectManager(
    fields,
    catalogView,
  );
  // 限时授权必须选择"未来"的过期时间, 否则后端会视为已过期而白跑一次审批。
  const expiresAtIsFuture = Boolean(fields.expiresAt) && new Date(fields.expiresAt) > new Date();
  const expiresAtError = fields.grantType === "timed" && Boolean(fields.expiresAt) && !expiresAtIsFuture;
  const canSubmit = Boolean(
      fields.appKey &&
      hasTarget &&
      lifecycleHasBaseGrant &&
      lifecycleSelectorIsComplete &&
      !currentGrantsTruncated &&
      selectedScopesAreComplete &&
      fields.selectedApproverUserIds.length > 0 &&
      fields.selectedApproverUserIds.length <= ACCESS_REQUEST_MAX_APPROVERS &&
      !fields.selectedApproverUserIds.includes(currentUserId) &&
      !managedUsersTargetHasMissingDirectManager &&
      fields.reason.trim().length > 0 &&
      fields.reason.length <= ACCESS_REQUEST_MAX_REASON_LENGTH &&
      (fields.grantType === "permanent" || expiresAtIsFuture) &&
      !submitMutation.isPending,
  );

  return buildAccessRequestFormResult(
    fields,
    catalogView,
    currentGrants,
    catalogQuery.isLoading || (lifecycleSelectorActive && currentGrantsQuery.isLoading),
    catalogQuery.error ?? (lifecycleSelectorActive ? currentGrantsQuery.error : null),
    submitMutation,
    canSubmit,
    expiresAtError,
    actions,
    currentGrantsTruncated,
  );
}

function useAccessRequestFields(): AccessRequestFields {
  const [requestType, setRequestType] = useState<AccessRequestType>("grant");
  const [appKey, setAppKey] = useState("");
  const [baseGrantId, setBaseGrantId] = useState("");
  const [baseGrantRevision, setBaseGrantRevision] = useState<number | null>(null);
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
    requestType,
    baseGrantId,
    baseGrantRevision,
    authorizationGroupKey,
    selectedPermissionKeys,
    selectedPermissionScopes,
    selectedApproverUserIds,
    expandedGroupKeys,
    approverSelectionWasEdited,
    grantType,
    expiresAt,
    reason,
    setRequestType,
    setAppKey,
    setBaseGrantId,
    setBaseGrantRevision,
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

function useAccessRequestSubmitMutation(
  fields: AccessRequestFields,
  catalogView: CatalogView,
): UseMutationResult<unknown, Error, void, unknown> {
  const pendingSubmission = useRef<{
    payload: string;
    idempotencyKey: string;
    draftRevision: number;
  } | null>(null);
  const draftRevision = useRef(0);
  // 草稿每次编辑推进 revision; 提交成功时仅当 revision 未变才 reset, 避免清空用户新草稿。
  useEffect(() => {
    draftRevision.current += 1;
  }, [
    fields.appKey,
    fields.requestType,
    fields.baseGrantId,
    fields.baseGrantRevision,
    fields.authorizationGroupKey,
    fields.selectedPermissionKeys,
    fields.selectedPermissionScopes,
    fields.selectedApproverUserIds,
    fields.grantType,
    fields.expiresAt,
    fields.reason,
  ]);
  return useMutation({
    mutationFn: () => {
      const payload = buildAccessRequestPayload(fields, catalogView);
      const serializedPayload = JSON.stringify(payload);
      if (pendingSubmission.current?.payload !== serializedPayload) {
        pendingSubmission.current = {
          payload: serializedPayload,
          idempotencyKey: crypto.randomUUID(),
          draftRevision: draftRevision.current,
        };
      }
      return apiRequest("/portal/api/v1/me/access-requests", {
        method: "POST",
        headers: { "Idempotency-Key": pendingSubmission.current.idempotencyKey },
        body: payload,
      });
    },
    onSuccess: () => {
      const submittedRevision = pendingSubmission.current?.draftRevision;
      pendingSubmission.current = null;
      // 仅当提交期间草稿未变时清空目标与理由, 避免旧成功响应抹掉新编辑。
      if (submittedRevision === draftRevision.current) {
        fields.setAuthorizationGroupKey("");
        fields.setSelectedPermissionKeys([]);
        fields.setSelectedPermissionScopes({});
        fields.setApproverSelectionWasEdited(false);
        fields.setReason("");
      }
      void queryClient.invalidateQueries({ queryKey: ["portal", "requests"] });
    },
  });
}

function buildAccessRequestFormResult(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  currentGrants: PortalGrantRow[],
  catalogIsLoading: boolean,
  catalogError: Error | null,
  submitMutation: UseMutationResult<unknown, Error, void, unknown>,
  canSubmit: boolean,
  expiresAtError: boolean,
  actions: AccessRequestActions,
  currentGrantsTruncated: boolean,
): AccessRequestFormResult {
  return {
    requestType: fields.requestType,
    appKey: fields.appKey,
    baseGrantId: fields.baseGrantId,
    authorizationGroupKey: fields.authorizationGroupKey,
    selectedPermissionKeys: fields.selectedPermissionKeys,
    selectedPermissionScopes: fields.selectedPermissionScopes,
    selectedApproverUserIds: fields.selectedApproverUserIds,
    expandedGroupKeys: fields.expandedGroupKeys,
    grantType: fields.grantType,
    expiresAt: fields.expiresAt,
    reason: fields.reason,
    apps: catalogView.apps,
    currentGrants,
    approverOptions: catalogView.approverOptions,
    authorizationGroups: catalogView.authorizationGroups,
    permissionGroups: catalogView.permissionGroups,
    ungroupedPermissions: catalogView.ungroupedPermissions,
    visiblePermissionKeys: catalogView.visiblePermissionKeys,
    groupCoveredSelectionKeys: buildGroupCoveredSelectionKeys(fields, catalogView),
    catalogIsLoading,
    catalogErrorMessage: currentGrantsTruncated ? "当前授权超过 100 条，不能在申请表中截断选择。" : catalogError ? catalogError.message : "",
    submitErrorMessage: submitMutation.error ? submitMutation.error.message : "",
    toastMessageKey: submitMutation.isSuccess ? "portal.request.submitted" : accessRequestToastMessageKey(fields, catalogView, catalogIsLoading),
    canSubmit,
    expiresAtError,
    isSubmitting: submitMutation.isPending,
    changeRequestType: actions.changeRequestType,
    changeBaseGrantId: actions.changeBaseGrantId,
    changeAppKey: actions.changeAppKey,
    changeAuthorizationGroupKey: actions.changeAuthorizationGroupKey,
    changeGrantType: fields.setGrantType,
    changeExpiresAt: fields.setExpiresAt,
    changeReason: (nextReason) => {
      fields.setReason((current) => {
        const next = typeof nextReason === "function" ? nextReason(current) : nextReason;
        return next.slice(0, ACCESS_REQUEST_MAX_REASON_LENGTH);
      });
    },
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

function buildGroupCoveredSelectionKeys(
  fields: AccessRequestFields,
  catalogView: CatalogView,
): string[] {
  const group = catalogView.authorizationGroups.find(
    (item) => item.key === fields.authorizationGroupKey,
  );
  return (group?.grants ?? []).map((grant) =>
    directGrantSelectionKey(grant.permission_key, grant.scope_key),
  );
}

function groupCoveredSelectionKeySet(groupKey: string, catalogView: CatalogView): Set<string> {
  const group = catalogView.authorizationGroups.find((item) => item.key === groupKey);
  return new Set(
    (group?.grants ?? []).map((grant) => directGrantSelectionKey(grant.permission_key, grant.scope_key)),
  );
}

function filterDirectGrantSelections(
  selectionKeys: string[],
  groupKey: string,
  catalogView: CatalogView,
): string[] {
  const coveredKeySet = groupCoveredSelectionKeySet(groupKey, catalogView);
  return uniqueStrings(selectionKeys)
    .filter((key) => !coveredKeySet.has(key));
}

function useLifecycleGrantInvariant(fields: AccessRequestFields, selectedBaseGrant: PortalGrantRow | undefined): void {
  const { requestType, setAppKey, setAuthorizationGroupKey, setBaseGrantRevision, setGrantType, setSelectedPermissionKeys } = fields;
  useEffect(() => {
    if (requestType === "grant" || !selectedBaseGrant) {
      return;
    }
    setAppKey(selectedBaseGrant.app_key ?? "");
    setBaseGrantRevision(selectedBaseGrant.grant_revision);
    if (requestType !== "renew") {
      return;
    }
    setAuthorizationGroupKey(selectedBaseGrant.groups[0]?.key ?? "");
    setSelectedPermissionKeys(
      selectedBaseGrant.grants
        .filter((item) => item.source_type === "direct")
        .map((item) => directGrantSelectionKey(item.permission, item.scope)),
    );
    setGrantType("timed");
  }, [
    requestType,
    selectedBaseGrant?.app_key,
    selectedBaseGrant?.grant_id,
    selectedBaseGrant?.grant_revision,
    selectedBaseGrant?.groups,
    selectedBaseGrant?.grants,
    setAppKey,
    setAuthorizationGroupKey,
    setBaseGrantRevision,
    setGrantType,
    setSelectedPermissionKeys,
  ]);
}


function buildAccessRequestActions(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  currentGrants: PortalGrantRow[],
  submit: () => void,
): AccessRequestActions {
  return {
    changeRequestType: (requestType: AccessRequestType) => {
      fields.setRequestType(requestType);
      fields.setBaseGrantId("");
      fields.setBaseGrantRevision(null);
      fields.setAppKey("");
      fields.setAuthorizationGroupKey("");
      fields.setSelectedPermissionKeys([]);
      fields.setSelectedPermissionScopes({});
      fields.setExpandedGroupKeys([]);
      fields.setSelectedApproverUserIds([]);
      fields.setApproverSelectionWasEdited(false);
      fields.setGrantType(requestType === "renew" ? "timed" : "permanent");
      fields.setExpiresAt("");
    },
    changeBaseGrantId: (grantId: string) => {
      const grant = currentGrants.find((item) => String(item.grant_id) === grantId);
      fields.setBaseGrantId(grantId);
      fields.setBaseGrantRevision(grant?.grant_revision ?? null);
      if (!grant) {
        return;
      }
      fields.setAppKey(grant.app_key ?? "");
      fields.setAuthorizationGroupKey(grant.groups[0]?.key ?? "");
      fields.setSelectedPermissionKeys(
        grant.grants
          .filter((item) => item.source_type === "direct")
          .map((item) => directGrantSelectionKey(item.permission, item.scope)),
      );
    },
    changeAppKey: (nextAppKey: string) => {
      fields.setAppKey(nextAppKey);
      fields.setBaseGrantId("");
      fields.setBaseGrantRevision(null);
      fields.setAuthorizationGroupKey("");
      fields.setSelectedPermissionKeys([]);
      fields.setSelectedPermissionScopes({});
      fields.setExpandedGroupKeys([]);
      fields.setSelectedApproverUserIds([]);
      fields.setApproverSelectionWasEdited(false);
    },
    changeAuthorizationGroupKey: (groupKey: string) => {
      fields.setAuthorizationGroupKey(groupKey);
      const coveredKeySet = groupCoveredSelectionKeySet(groupKey, catalogView);
      fields.setSelectedPermissionKeys((current) => current.filter((key) => !coveredKeySet.has(key)));
    },
    selectPermissionKeys: (keys: string[]) => {
      const coveredKeySet = groupCoveredSelectionKeySet(fields.authorizationGroupKey, catalogView);
      fields.setSelectedPermissionKeys((current) =>
        uniqueStrings([...current, ...keys])
          .filter((key) => !coveredKeySet.has(key)),
      );
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
      fields.setSelectedApproverUserIds((current) => {
        if (!current.includes(userId) && current.length >= ACCESS_REQUEST_MAX_APPROVERS) {
          return current;
        }
        return toggleListItem(current, userId);
      });
    },
    changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => {
      fields.setSelectedPermissionKeys((current) => {
        const shouldSelect = !selectedScopeKeysForPermission(permission, current).includes(scopeKey);
        return filterDirectGrantSelections(
          nextPermissionScopeSelection(permission, scopeKey, shouldSelect, current),
          fields.authorizationGroupKey,
          catalogView,
        );
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
        return filterDirectGrantSelections(next, fields.authorizationGroupKey, catalogView);
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

function buildAccessRequestPayload(values: AccessRequestPayloadValues, catalogView: CatalogView): JsonObject {
  assertAccessRequestPayloadLimits(values);
  const coveredKeySet = groupCoveredSelectionKeySet(values.authorizationGroupKey, catalogView);
  const overlappingSelection = values.selectedPermissionKeys.find((key) => coveredKeySet.has(key));
  if (overlappingSelection) {
    throw new Error(`直接权限与权限组覆盖范围重复: ${overlappingSelection}`);
  }
  const baseGrant: JsonObject = values.requestType === "grant"
    ? {}
    : {
        base_grant_id: Number(values.baseGrantId),
        base_grant_revision: values.baseGrantRevision,
      };
  return {
    app_key: values.appKey,
    request_type: values.requestType,
    ...baseGrant,
    authorization_group_keys: values.authorizationGroupKey ? [values.authorizationGroupKey] : [],
    direct_grants: values.selectedPermissionKeys.map((selectionKey) => buildDirectGrantPayload(selectionKey)),
    approver_user_ids: values.selectedApproverUserIds,
    grant_type: values.grantType,
    grant_expires_at: values.grantType === "timed" && values.expiresAt ? new Date(values.expiresAt).toISOString() : null,
    reason: values.reason.trim(),
  };
}

function assertAccessRequestPayloadLimits(values: AccessRequestPayloadValues): void {
  if (values.requestType !== "grant" && (!values.baseGrantId || values.baseGrantRevision === null)) {
    throw new Error("生命周期申请缺少基础授权。");
  }
  if (values.selectedApproverUserIds.length > ACCESS_REQUEST_MAX_APPROVERS) {
    throw new Error(`审批人不能超过 ${ACCESS_REQUEST_MAX_APPROVERS} 名`);
  }
  if (values.reason.length > ACCESS_REQUEST_MAX_REASON_LENGTH) {
    throw new Error(`申请原因不能超过 ${ACCESS_REQUEST_MAX_REASON_LENGTH} 个字符`);
  }
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
  if (!permissionKey || !scopeKey) {
    throw new Error("直接权限选择的 permission key 和 scope key 不能为空");
  }
  return JSON.stringify([permissionKey, scopeKey]);
}

export function directGrantSelectionPermissionKey(selectionKey: string): string {
  return parseDirectGrantSelectionKey(selectionKey)[0];
}

function directGrantSelectionScopeKey(selectionKey: string): string | null {
  return parseDirectGrantSelectionKey(selectionKey)[1];
}

function parseDirectGrantSelectionKey(selectionKey: string): readonly [string, string] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(selectionKey);
  } catch {
    throw new Error(`直接权限选择结构无效: ${selectionKey}`);
  }
  if (
    !Array.isArray(parsed)
    || parsed.length !== 2
    || typeof parsed[0] !== "string"
    || !parsed[0]
    || typeof parsed[1] !== "string"
    || !parsed[1]
  ) {
    throw new Error(`直接权限选择结构无效: ${selectionKey}`);
  }
  return [parsed[0], parsed[1]];
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

function permissionSelectionKeys(permission: ScopedPermissionItem): string[] {
  return permissionScopeKeys(permission).map((scopeKey) => directGrantSelectionKey(permission.key, scopeKey));
}

function permissionScopeSelectionKey(permission: ScopedPermissionItem, scopeKey: string): string | null {
  return (permission.scopes ?? []).some((scope) => scope.key === scopeKey)
    ? directGrantSelectionKey(permission.key, scopeKey)
    : null;
}

function permissionScopeKeys(permission: ScopedPermissionItem): string[] {
  const scopes = permission.scopes ?? [];
  return scopes.map((scope) => scope.key);
}

function selectedScopeKeysForPermission(permission: ScopedPermissionItem, selectedPermissionKeys: string[]): string[] {
  const selectedKeySet = new Set(selectedPermissionKeys);
  return (permission.scopes ?? [])
    .filter((scope) => selectedKeySet.has(directGrantSelectionKey(permission.key, scope.key)))
    .map((scope) => scope.key);
}

function nextPermissionScopeSelection(
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

function useGroupCoverageInvariant(fields: AccessRequestFields, catalogView: CatalogView): void {
  const { authorizationGroupKey, setSelectedPermissionKeys } = fields;
  const coveredSelectionKeys = useMemo(
    () => Array.from(groupCoveredSelectionKeySet(authorizationGroupKey, catalogView)),
    [authorizationGroupKey, catalogView],
  );

  useEffect(() => {
    if (coveredSelectionKeys.length === 0) {
      return;
    }
    const coveredKeySet = new Set(coveredSelectionKeys);
    setSelectedPermissionKeys((current) => {
      const next = current.filter((key) => !coveredKeySet.has(key));
      return listsAreEqual(current, next) ? current : next;
    });
  }, [coveredSelectionKeys, setSelectedPermissionKeys]);
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
    return targetApprovers.filter((userId) => userId !== currentUserId).slice(0, ACCESS_REQUEST_MAX_APPROVERS);
  }
  if (selectedManagedUsersTargetHasMissingDirectManager(values, catalogView)) {
    return [];
  }
  return uniqueUserIds(app?.default_approver_user_ids ?? [])
    .filter((userId) => userId !== currentUserId)
    .slice(0, ACCESS_REQUEST_MAX_APPROVERS);
}

function accessRequestToastMessageKey(fields: AccessRequestFields, catalogView: CatalogView, catalogIsLoading: boolean): MessageKey | "" {
  if (selectedManagedUsersTargetHasMissingDirectManager(fields, catalogView)) {
    return "portal.request.approverMissing";
  }
  return noDirectPermissionsToastMessageKey(fields, catalogView, catalogIsLoading);
}

function noDirectPermissionsToastMessageKey(fields: AccessRequestFields, catalogView: CatalogView, catalogIsLoading: boolean): MessageKey | "" {
  if (catalogIsLoading || !fields.appKey || catalogView.visiblePermissionKeys.length > 0) {
    return "";
  }
  return "portal.request.noDirectPermissions";
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
  if (authorizationGroup?.grants?.some((grant) => grant.scope_key === "MANAGED_USERS")) {
    targets.push(authorizationGroup);
  }
  const directGrantPermissionKeys = Array.from(new Set(
    values.selectedPermissionKeys
      .filter((key) => directGrantSelectionScopeKey(key) === "MANAGED_USERS")
      .map((key) => directGrantSelectionPermissionKey(key)),
  ));
  for (const permissionKey of directGrantPermissionKeys) {
    const permission = catalogView.permissionsByKey[permissionKey];
    if (permission) {
      targets.push(permission);
    }
  }
  return targets;
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
