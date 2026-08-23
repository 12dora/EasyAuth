import type { PortalGrantRow } from "../portalListPayload";
import {
  collectScopedGroupPermissions,
  descendantGroupKeys,
  filterDirectGrantSelections,
  groupCoveredSelectionKeySet,
} from "./accessRequestCatalog";
import {
  directGrantSelectionKey,
  nextPermissionScopeCascadeClearSelection,
  nextPermissionScopeSelection,
  permissionScopeSelectionKey,
  selectedScopeKeysForPermission,
  toggleListItem,
  uniqueStrings,
} from "./accessRequestSelection";
import {
  ACCESS_REQUEST_MAX_APPROVERS,
  type AccessRequestActions,
  type AccessRequestFields,
  type AccessRequestType,
  type CatalogView,
  type ScopedPermissionGroupItem,
  type ScopedPermissionItem,
} from "./accessRequestTypes";

export function buildAccessRequestActions(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  currentGrants: PortalGrantRow[],
  submit: () => void,
): AccessRequestActions {
  return {
    ...buildTargetActions(fields, currentGrants),
    ...buildPermissionSelectionActions(fields, catalogView),
    ...buildGroupExpansionActions(fields, catalogView),
    ...buildApproverActions(fields),
    submit,
  };
}

type TargetActions = Pick<AccessRequestActions, "changeRequestType" | "changeBaseGrantId" | "changeAppKey">;

function buildTargetActions(fields: AccessRequestFields, currentGrants: PortalGrantRow[]): TargetActions {
  return {
    changeRequestType: (requestType: AccessRequestType) => {
      fields.setRequestType(requestType);
      resetTargetDraft(fields, "");
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
      resetTargetDraft(fields, nextAppKey);
    },
  };
}

/** 换申请类型或换应用都会作废整张草稿: 基础授权、权限组、直接权限、展开态与审批人一并清空。 */
function resetTargetDraft(fields: AccessRequestFields, nextAppKey: string): void {
  fields.setAppKey(nextAppKey);
  fields.setBaseGrantId("");
  fields.setBaseGrantRevision(null);
  fields.setAuthorizationGroupKey("");
  fields.setSelectedPermissionKeys([]);
  fields.setSelectedPermissionScopes({});
  fields.setExpandedGroupKeys([]);
  fields.setSelectedApproverUserIds([]);
  fields.setApproverSelectionWasEdited(false);
}

type PermissionSelectionActions = Pick<
  AccessRequestActions,
  "changeAuthorizationGroupKey" | "selectPermissionKeys" | "clearPermissionKeys" | "changePermissionScope" | "changePermissionGroupScope"
>;

function buildPermissionSelectionActions(fields: AccessRequestFields, catalogView: CatalogView): PermissionSelectionActions {
  return {
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
  };
}

type GroupExpansionActions = Pick<AccessRequestActions, "expandGroups" | "collapseGroups" | "toggleGroup">;

function buildGroupExpansionActions(fields: AccessRequestFields, catalogView: CatalogView): GroupExpansionActions {
  return {
    expandGroups: (keys: string[]) => {
      fields.setExpandedGroupKeys((current) => uniqueStrings([...current, ...keys]));
    },
    collapseGroups: (keys: string[]) => {
      const keySet = new Set(keys.flatMap((key) => [key, ...descendantGroupKeys(catalogView.permissionGroups, key)]));
      fields.setExpandedGroupKeys((current) => current.filter((key) => !keySet.has(key)));
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
  };
}

function buildApproverActions(fields: AccessRequestFields): Pick<AccessRequestActions, "toggleApprover"> {
  return {
    toggleApprover: (userId: string) => {
      fields.setApproverSelectionWasEdited(true);
      fields.setSelectedApproverUserIds((current) => {
        if (!current.includes(userId) && current.length >= ACCESS_REQUEST_MAX_APPROVERS) {
          return current;
        }
        return toggleListItem(current, userId);
      });
    },
  };
}
