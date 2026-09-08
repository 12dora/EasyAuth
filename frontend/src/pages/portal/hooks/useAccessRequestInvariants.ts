import { useEffect, useMemo, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { PortalGrantRow } from "../portalListPayload";
import { applyBaseGrantToDraft } from "./accessRequestActions";
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
  const { authorizationGroupKeys, setSelectedPermissionKeys } = fields;
  const coveredSelectionKeys = useMemo(
    () => Array.from(groupCoveredSelectionKeySet(authorizationGroupKeys, catalogView)),
    [authorizationGroupKeys, catalogView],
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
  const { appKey, authorizationGroupKeys, selectedPermissionKeys, approverSelectionWasEdited, setSelectedApproverUserIds } = fields;
  const defaultApproverUserIds = useMemo(
    () => buildDefaultApproverUserIds(fields, catalogView, currentUserId),
    [catalogView, appKey, authorizationGroupKeys, selectedPermissionKeys, currentUserId],
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

/**
 * 授权列表到齐之后重新判定申请类型。
 *
 * 应用选择器在"我的授权"到达之前就能用: 那一刻列表还是空的, "这个应用没有生效授权"的结论可能是错的,
 * 于是表单会停在一份后端必拒的新增申请上(submission_validation._validate_no_current_grant)。
 * 列表到齐后按同一条规则重算一次: 有生效授权就转成变更申请并带出现状, 没有就回落成新增申请。
 * 已经选好基础授权(含撤销/续期)的草稿不动。
 */
export function useCurrentGrantForAppInvariant(
  fields: AccessRequestFields,
  currentGrants: PortalGrantRow[],
  currentGrantsAreLoaded: boolean,
): void {
  const { appKey, baseGrantId, requestType } = fields;
  // 每次"选中某个应用"只判一次: 判过之后草稿归用户, 重算会把用户的增删原样冲掉。
  const settledAppKeyRef = useRef("");
  useEffect(() => {
    if (!currentGrantsAreLoaded || appKey === "" || settledAppKeyRef.current === appKey) {
      return;
    }
    settledAppKeyRef.current = appKey;
    if (baseGrantId !== "" || (requestType !== "grant" && requestType !== "change")) {
      // 选应用时已经判过(changeAppKey), 或者是撤销/续期这种由基础授权定目标的申请。
      return;
    }
    const grant = currentGrants.find((item) => item.app_key === appKey);
    if (!grant) {
      if (requestType === "change") {
        fields.setRequestType("grant");
      }
      return;
    }
    fields.setRequestType("change");
    fields.setBaseGrantId(String(grant.grant_id));
    applyBaseGrantToDraft(fields, grant);
    // fields 每次渲染都是新对象, 但其中的 setter 是稳定的: 依赖只列真正会变的那几项。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentGrantsAreLoaded, currentGrants, appKey, baseGrantId, requestType]);
}

export function useLifecycleGrantInvariant(fields: AccessRequestFields, selectedBaseGrant: PortalGrantRow | undefined): void {
  const { requestType, setAppKey, setAuthorizationGroupKeys, setBaseGrantRevision, setGrantType, setSelectedPermissionKeys } = fields;
  useEffect(() => {
    if (requestType === "grant" || !selectedBaseGrant) {
      return;
    }
    setAppKey(selectedBaseGrant.app_key ?? "");
    setBaseGrantRevision(selectedBaseGrant.grant_revision);
    if (requestType !== "renew") {
      return;
    }
    setAuthorizationGroupKeys(selectedBaseGrant.groups.map((group) => group.key));
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
    setAuthorizationGroupKeys,
    setBaseGrantRevision,
    setGrantType,
    setSelectedPermissionKeys,
  ]);
}
