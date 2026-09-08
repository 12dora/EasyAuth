import type { UseMutationResult } from "@tanstack/react-query";

import type { MessageKey } from "../../../i18n/messages";
import type { PortalGrantRow } from "../portalListPayload";
import { groupCoveredSelectionKeys } from "./accessRequestCatalog";
import { revokeBaseGrantSnapshot } from "./accessRequestTargetLock";
import {
  ACCESS_REQUEST_MAX_REASON_LENGTH,
  type AccessRequestActions,
  type AccessRequestFields,
  type AccessRequestFormResult,
  type CatalogView,
} from "./accessRequestTypes";
import { accessRequestNoticeMessageKey } from "./accessRequestValidation";

export interface AccessRequestFormResultInput {
  fields: AccessRequestFields;
  catalogView: CatalogView;
  currentGrants: PortalGrantRow[];
  selectedBaseGrant: PortalGrantRow | undefined;
  catalogIsLoading: boolean;
  catalogError: Error | null;
  submitMutation: UseMutationResult<unknown, Error, void, unknown>;
  canSubmit: boolean;
  expiresAtError: boolean;
  actions: AccessRequestActions;
  prefillErrorMessageKey: MessageKey | "";
}

export function buildAccessRequestFormResult(input: AccessRequestFormResultInput): AccessRequestFormResult {
  return {
    ...draftValues(input.fields),
    ...catalogSnapshot(input.fields, input.catalogView, input.currentGrants),
    revokeBaseGrant: revokeBaseGrantSnapshot(input.fields.requestType, input.selectedBaseGrant),
    baseGrantLockedToApp:
      input.fields.requestType === "change"
      && input.fields.appKey !== ""
      && input.currentGrants.some((grant) => grant.app_key === input.fields.appKey),
    ...submissionStatus(input),
    prefillErrorMessageKey: input.prefillErrorMessageKey,
    ...formHandlers(input.fields, input.actions),
  };
}

type DraftValues = Pick<
  AccessRequestFormResult,
  | "requestType"
  | "appKey"
  | "baseGrantId"
  | "authorizationGroupKeys"
  | "selectedPermissionKeys"
  | "selectedPermissionScopes"
  | "selectedApproverUserIds"
  | "expandedGroupKeys"
  | "grantType"
  | "expiresAt"
  | "reason"
>;

function draftValues(fields: AccessRequestFields): DraftValues {
  return {
    requestType: fields.requestType,
    appKey: fields.appKey,
    baseGrantId: fields.baseGrantId,
    authorizationGroupKeys: fields.authorizationGroupKeys,
    selectedPermissionKeys: fields.selectedPermissionKeys,
    selectedPermissionScopes: fields.selectedPermissionScopes,
    selectedApproverUserIds: fields.selectedApproverUserIds,
    expandedGroupKeys: fields.expandedGroupKeys,
    grantType: fields.grantType,
    expiresAt: fields.expiresAt,
    reason: fields.reason,
  };
}

type CatalogSnapshot = Pick<
  AccessRequestFormResult,
  | "apps"
  | "currentGrants"
  | "approverOptions"
  | "authorizationGroups"
  | "permissionGroups"
  | "ungroupedPermissions"
  | "visiblePermissionKeys"
  | "groupCoveredSelectionKeys"
>;

function catalogSnapshot(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  currentGrants: PortalGrantRow[],
): CatalogSnapshot {
  return {
    apps: catalogView.apps,
    currentGrants,
    approverOptions: catalogView.approverOptions,
    authorizationGroups: catalogView.authorizationGroups,
    permissionGroups: catalogView.permissionGroups,
    ungroupedPermissions: catalogView.ungroupedPermissions,
    visiblePermissionKeys: catalogView.visiblePermissionKeys,
    groupCoveredSelectionKeys: groupCoveredSelectionKeys(fields.authorizationGroupKeys, catalogView),
  };
}

type SubmissionStatus = Pick<
  AccessRequestFormResult,
  "catalogIsLoading" | "catalogErrorMessage" | "submitErrorMessage" | "noticeMessageKey" | "canSubmit" | "expiresAtError" | "isSubmitting"
>;

function submissionStatus(input: AccessRequestFormResultInput): SubmissionStatus {
  const { submitMutation } = input;
  return {
    catalogIsLoading: input.catalogIsLoading,
    catalogErrorMessage: input.catalogError ? input.catalogError.message : "",
    submitErrorMessage: submitMutation.error ? submitMutation.error.message : "",
    noticeMessageKey: accessRequestNoticeMessageKey(
      input.fields,
      input.catalogView,
      input.catalogIsLoading,
      input.selectedBaseGrant,
    ),
    canSubmit: input.canSubmit,
    expiresAtError: input.expiresAtError,
    isSubmitting: submitMutation.isPending,
  };
}

type FormHandlers = Pick<
  AccessRequestFormResult,
  | "changeRequestType"
  | "changeBaseGrantId"
  | "changeAppKey"
  | "changeAuthorizationGroupKeys"
  | "changeGrantType"
  | "changeExpiresAt"
  | "changeReason"
  | "selectPermissionKeys"
  | "clearPermissionKeys"
  | "expandGroups"
  | "collapseGroups"
  | "toggleApprover"
  | "changePermissionScope"
  | "changePermissionGroupScope"
  | "toggleGroup"
  | "submit"
>;

function formHandlers(fields: AccessRequestFields, actions: AccessRequestActions): FormHandlers {
  return {
    changeRequestType: actions.changeRequestType,
    changeBaseGrantId: actions.changeBaseGrantId,
    changeAppKey: actions.changeAppKey,
    changeAuthorizationGroupKeys: actions.changeAuthorizationGroupKeys,
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
