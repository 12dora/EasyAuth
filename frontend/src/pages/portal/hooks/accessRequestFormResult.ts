import type { UseMutationResult } from "@tanstack/react-query";

import type { PortalGrantRow } from "../portalListPayload";
import { groupCoveredSelectionKeys } from "./accessRequestCatalog";
import {
  ACCESS_REQUEST_MAX_REASON_LENGTH,
  type AccessRequestActions,
  type AccessRequestFields,
  type AccessRequestFormResult,
  type CatalogView,
} from "./accessRequestTypes";
import { accessRequestToastMessageKey } from "./accessRequestValidation";

export interface AccessRequestFormResultInput {
  fields: AccessRequestFields;
  catalogView: CatalogView;
  currentGrants: PortalGrantRow[];
  catalogIsLoading: boolean;
  catalogError: Error | null;
  submitMutation: UseMutationResult<unknown, Error, void, unknown>;
  canSubmit: boolean;
  expiresAtError: boolean;
  actions: AccessRequestActions;
  currentGrantsTruncated: boolean;
}

export function buildAccessRequestFormResult(input: AccessRequestFormResultInput): AccessRequestFormResult {
  return {
    ...draftValues(input.fields),
    ...catalogSnapshot(input.fields, input.catalogView, input.currentGrants),
    ...submissionStatus(input),
    ...formHandlers(input.fields, input.actions),
  };
}

type DraftValues = Pick<
  AccessRequestFormResult,
  | "requestType"
  | "appKey"
  | "baseGrantId"
  | "authorizationGroupKey"
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
    authorizationGroupKey: fields.authorizationGroupKey,
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
    groupCoveredSelectionKeys: groupCoveredSelectionKeys(fields.authorizationGroupKey, catalogView),
  };
}

type SubmissionStatus = Pick<
  AccessRequestFormResult,
  "catalogIsLoading" | "catalogErrorMessage" | "submitErrorMessage" | "toastMessageKey" | "canSubmit" | "expiresAtError" | "isSubmitting"
>;

function submissionStatus(input: AccessRequestFormResultInput): SubmissionStatus {
  const { submitMutation } = input;
  return {
    catalogIsLoading: input.catalogIsLoading,
    catalogErrorMessage: catalogErrorMessage(input.catalogError, input.currentGrantsTruncated),
    submitErrorMessage: submitMutation.error ? submitMutation.error.message : "",
    toastMessageKey: submitMutation.isSuccess
      ? "portal.request.submitted"
      : accessRequestToastMessageKey(input.fields, input.catalogView, input.catalogIsLoading),
    canSubmit: input.canSubmit,
    expiresAtError: input.expiresAtError,
    isSubmitting: submitMutation.isPending,
  };
}

function catalogErrorMessage(catalogError: Error | null, currentGrantsTruncated: boolean): string {
  if (currentGrantsTruncated) {
    return "当前授权超过 100 条，不能在申请表中截断选择。";
  }
  return catalogError ? catalogError.message : "";
}

type FormHandlers = Pick<
  AccessRequestFormResult,
  | "changeRequestType"
  | "changeBaseGrantId"
  | "changeAppKey"
  | "changeAuthorizationGroupKey"
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
