import type { MessageKey } from "../../../i18n/messages";
import type { PortalGrantRow } from "../portalListPayload";
import { selectedManagedUsersTargetHasMissingDirectManager } from "./accessRequestApprovers";
import { hasSelectionScope } from "./accessRequestSelection";
import { revokeBaseGrantSnapshot, revokeTargetIsStrictReduction } from "./accessRequestTargetLock";
import {
  ACCESS_REQUEST_MAX_APPROVERS,
  ACCESS_REQUEST_MAX_AUTHORIZATION_GROUPS,
  ACCESS_REQUEST_MAX_REASON_LENGTH,
  type AccessRequestPayloadValues,
  type CatalogView,
} from "./accessRequestTypes";

export interface AccessRequestSubmitGate {
  values: AccessRequestPayloadValues;
  catalogView: CatalogView;
  selectedBaseGrant: PortalGrantRow | undefined;
  currentGrantsTruncated: boolean;
  isSubmitting: boolean;
  currentUserId: string;
  /** 与 accessRequestExpiresAtError 共享的同一次时钟读数, 避免两者对"是否已过期"给出互相矛盾的结论。 */
  grantTermIsFuture: boolean;
}

export function accessRequestCanSubmit(gate: AccessRequestSubmitGate): boolean {
  // 与原实现一致地先行求值: 选择结构非法时立即抛错, 不因前置条件短路而被吞掉。
  const selectedScopesAreComplete = gate.values.selectedPermissionKeys.every((key) => hasSelectionScope(key));
  const managedUsersTargetHasMissingDirectManager = selectedManagedUsersTargetHasMissingDirectManager(
    gate.values,
    gate.catalogView,
  );
  return (
    hasRequestTarget(gate.values)
    && authorizationGroupCountIsWithinLimit(gate.values)
    && lifecycleSelectionIsComplete(gate.values, gate.selectedBaseGrant, gate.currentGrantsTruncated)
    && revokeTargetReducesBaseGrant(gate.values, gate.selectedBaseGrant)
    && selectedScopesAreComplete
    && !managedUsersTargetHasMissingDirectManager
    && approverSelectionIsValid(gate.values, gate.currentUserId)
    && reasonIsValid(gate.values)
    && grantTermIsValid(gate.values, gate.grantTermIsFuture)
    && !gate.isSubmitting
  );
}

export function accessRequestExpiresAtError(
  values: AccessRequestPayloadValues,
  grantTermIsFuture: boolean,
): boolean {
  return values.grantType === "timed" && Boolean(values.expiresAt) && !grantTermIsFuture;
}

export function accessRequestToastMessageKey(
  values: AccessRequestPayloadValues,
  catalogView: CatalogView,
  catalogIsLoading: boolean,
  selectedBaseGrant: PortalGrantRow | undefined,
): MessageKey | "" {
  // 提交闸门里"目标本身不合法"的两种情况优先说清楚: 否则提交按钮只是灰着, 用户看不出为什么。
  if (!authorizationGroupCountIsWithinLimit(values)) {
    return "portal.request.tooManyAuthorizationGroups";
  }
  if (selectedManagedUsersTargetHasMissingDirectManager(values, catalogView)) {
    return "portal.request.approverMissing";
  }
  if (!revokeTargetReducesBaseGrant(values, selectedBaseGrant)) {
    return "portal.request.revokeKeepsWholeGrant";
  }
  if (catalogIsLoading || !values.appKey || catalogView.visiblePermissionKeys.length > 0) {
    return "";
  }
  return "portal.request.noDirectPermissions";
}

function hasRequestTarget(values: AccessRequestPayloadValues): boolean {
  if (!values.appKey) {
    return false;
  }
  if (values.requestType === "revoke") {
    return true;
  }
  return values.authorizationGroupKeys.length > 0 || values.selectedPermissionKeys.length > 0;
}

/** 后端 AccessRequestSubmitPayload.authorization_group_keys 有 max_length, 超了整个载荷都会被拒。 */
function authorizationGroupCountIsWithinLimit(values: AccessRequestPayloadValues): boolean {
  return values.authorizationGroupKeys.length <= ACCESS_REQUEST_MAX_AUTHORIZATION_GROUPS;
}

/** 撤销必须真的减少授权; 其余申请类型不受基础授权约束。 */
function revokeTargetReducesBaseGrant(
  values: AccessRequestPayloadValues,
  selectedBaseGrant: PortalGrantRow | undefined,
): boolean {
  const snapshot = revokeBaseGrantSnapshot(values.requestType, selectedBaseGrant);
  return snapshot === null || revokeTargetIsStrictReduction(values, snapshot);
}

function lifecycleSelectionIsComplete(
  values: AccessRequestPayloadValues,
  selectedBaseGrant: PortalGrantRow | undefined,
  currentGrantsTruncated: boolean,
): boolean {
  if (currentGrantsTruncated) {
    return false;
  }
  if (values.requestType === "grant") {
    return true;
  }
  if (!selectedBaseGrant) {
    return false;
  }
  return values.requestType !== "renew" || selectedBaseGrant.grant_type === "timed";
}

function approverSelectionIsValid(values: AccessRequestPayloadValues, currentUserId: string): boolean {
  const approverUserIds = values.selectedApproverUserIds;
  return approverUserIds.length > 0
    && approverUserIds.length <= ACCESS_REQUEST_MAX_APPROVERS
    && !approverUserIds.includes(currentUserId);
}

function reasonIsValid(values: AccessRequestPayloadValues): boolean {
  return values.reason.trim().length > 0 && values.reason.length <= ACCESS_REQUEST_MAX_REASON_LENGTH;
}

function grantTermIsValid(values: AccessRequestPayloadValues, grantTermIsFuture: boolean): boolean {
  return values.grantType === "permanent" || grantTermIsFuture;
}

// 限时授权必须选择"未来"的过期时间, 否则后端会视为已过期而白跑一次审批。
export function accessRequestExpiresAtIsFuture(values: AccessRequestPayloadValues): boolean {
  return Boolean(values.expiresAt) && new Date(values.expiresAt) > new Date();
}
