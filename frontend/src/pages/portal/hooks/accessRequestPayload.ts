import type { JsonObject } from "../../../lib/api";
import { groupCoveredSelectionKeySet } from "./accessRequestCatalog";
import { directGrantSelectionPermissionKey, directGrantSelectionScopeKey } from "./accessRequestSelection";
import {
  ACCESS_REQUEST_MAX_APPROVERS,
  ACCESS_REQUEST_MAX_AUTHORIZATION_GROUPS,
  ACCESS_REQUEST_MAX_REASON_LENGTH,
  type AccessRequestPayloadValues,
  type CatalogView,
} from "./accessRequestTypes";

export function buildAccessRequestPayload(
  values: AccessRequestPayloadValues,
  catalogView: CatalogView,
  locked: { groupKeys?: readonly string[]; selectionKeys?: readonly string[] } = {},
): JsonObject {
  const lockedGroupKeySet = new Set(locked.groupKeys ?? []);
  const lockedSelectionKeySet = new Set(locked.selectionKeys ?? []);
  const authorizationGroupKeys = values.authorizationGroupKeys.filter((key) => !lockedGroupKeySet.has(key));
  const selectedPermissionKeys = values.selectedPermissionKeys.filter((key) => !lockedSelectionKeySet.has(key));
  const draft: AccessRequestPayloadValues = { ...values, authorizationGroupKeys, selectedPermissionKeys };
  assertAccessRequestPayloadLimits(draft);
  const coveredKeySet = groupCoveredSelectionKeySet(draft.authorizationGroupKeys, catalogView);
  const overlappingSelection = draft.selectedPermissionKeys.find((key) => coveredKeySet.has(key));
  if (overlappingSelection) {
    throw new Error(`直接权限与权限组覆盖范围重复: ${overlappingSelection}`);
  }
  const baseGrant: JsonObject = draft.requestType === "grant"
    ? {}
    : {
        base_grant_id: Number(draft.baseGrantId),
        base_grant_revision: draft.baseGrantRevision,
      };
  return {
    app_key: draft.appKey,
    request_type: draft.requestType,
    ...baseGrant,
    authorization_group_keys: draft.authorizationGroupKeys,
    direct_grants: draft.selectedPermissionKeys.map((selectionKey) => buildDirectGrantPayload(selectionKey)),
    approver_user_ids: draft.selectedApproverUserIds,
    grant_type: draft.grantType,
    grant_expires_at: draft.grantType === "timed" && draft.expiresAt ? new Date(draft.expiresAt).toISOString() : null,
    reason: draft.reason.trim(),
  };
}

function assertAccessRequestPayloadLimits(values: AccessRequestPayloadValues): void {
  if (values.requestType !== "grant" && (!values.baseGrantId || values.baseGrantRevision === null)) {
    throw new Error("生命周期申请缺少基础授权。");
  }
  if (values.authorizationGroupKeys.length > ACCESS_REQUEST_MAX_AUTHORIZATION_GROUPS) {
    throw new Error(`权限组不能超过 ${ACCESS_REQUEST_MAX_AUTHORIZATION_GROUPS} 个`);
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
