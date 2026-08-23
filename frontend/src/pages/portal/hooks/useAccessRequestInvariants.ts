import { useEffect, useMemo } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { PortalGrantRow } from "../portalListPayload";
import { buildDefaultApproverUserIds } from "./accessRequestApprovers";
import { groupCoveredSelectionKeySet, nextDefaultPermissionScopes } from "./accessRequestCatalog";
import { directGrantSelectionKey, listsAreEqual } from "./accessRequestSelection";
import type { AccessRequestFields, CatalogView } from "./accessRequestTypes";

export function useDefaultSingleScopes(
  setSelectedPermissionScopes: Dispatch<SetStateAction<Record<string, string>>>,
  catalogView: CatalogView,
): void {
  const { scopesByPermissionKey, visiblePermissionKeys } = catalogView;
  useEffect(() => {
    setSelectedPermissionScopes((current) =>
      nextDefaultPermissionScopes(current, visiblePermissionKeys, scopesByPermissionKey),
    );
  }, [scopesByPermissionKey, visiblePermissionKeys, setSelectedPermissionScopes]);
}

export function useGroupCoverageInvariant(fields: AccessRequestFields, catalogView: CatalogView): void {
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

export function useDefaultApprovers(fields: AccessRequestFields, catalogView: CatalogView, currentUserId: string): void {
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

export function useLifecycleGrantInvariant(fields: AccessRequestFields, selectedBaseGrant: PortalGrantRow | undefined): void {
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
