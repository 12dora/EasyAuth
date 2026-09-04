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

export function buildAccessRequestPayload(values: AccessRequestPayloadValues, catalogView: CatalogView): JsonObject {
  assertAccessRequestPayloadLimits(values);
  const coveredKeySet = groupCoveredSelectionKeySet(values.authorizationGroupKeys, catalogView);
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
    authorization_group_keys: values.authorizationGroupKeys,
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
