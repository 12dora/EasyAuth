import type { PortalGrantRow } from "../portalListPayload";
import {
  collectScopedGroupPermissions,
  descendantGroupKeys,
  filterDirectGrantSelections,
  groupCoveredSelectionKeys,
  groupCoveredSelectionKeySet,
} from "./accessRequestCatalog";
import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
  directGrantSelectionScopeKey,
  nextPermissionScopeCascadeClearSelection,
  nextPermissionScopeSelection,
  permissionScopeSelectionKey,
  selectedScopeKeysForPermission,
  toggleListItem,
  uniqueStrings,
} from "./accessRequestSelection";
import {
  ACCESS_REQUEST_MAX_APPROVERS,
  defaultGrantTypeForRequestType,
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
      fields.setGrantType(defaultGrantTypeForRequestType(requestType));
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
      // 一条授权可以挂多个权限组(入职、交接、控制台授权都会写 AccessGrantGroup), 必须整套带进草稿:
      // 少带一个, 提交出去的变更就会把它当成"要撤掉"。
      fields.setAuthorizationGroupKeys(grant.groups.map((group) => group.key));
      fields.setGroupMaterializationNoticeKey("");
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
  fields.setAuthorizationGroupKeys([]);
  fields.setSelectedPermissionKeys([]);
  fields.setSelectedPermissionScopes({});
  fields.setExpandedGroupKeys([]);
  fields.setSelectedApproverUserIds([]);
  fields.setApproverSelectionWasEdited(false);
  fields.setGroupMaterializationNoticeKey("");
}

type PermissionSelectionActions = Pick<
  AccessRequestActions,
  "changeAuthorizationGroupKeys" | "selectPermissionKeys" | "clearPermissionKeys" | "changePermissionScope" | "changePermissionGroupScope"
>;

function buildPermissionSelectionActions(fields: AccessRequestFields, catalogView: CatalogView): PermissionSelectionActions {
  return {
    changeAuthorizationGroupKeys: (groupKeys: string[]) => {
      const nextGroupKeys = uniqueStrings(groupKeys);
      fields.setAuthorizationGroupKeys(nextGroupKeys);
      fields.setGroupMaterializationNoticeKey("");
      const coveredKeySet = groupCoveredSelectionKeySet(nextGroupKeys, catalogView);
      fields.setSelectedPermissionKeys((current) => current.filter((key) => !coveredKeySet.has(key)));
    },
    selectPermissionKeys: (keys: string[]) => {
      applySelectionChange(fields, catalogView, (current) => uniqueStrings([...current, ...keys]));
    },
    clearPermissionKeys: (keys: string[]) => {
      const keySet = new Set(keys);
      applySelectionChange(fields, catalogView, (current) => current.filter((key) => !keySet.has(key)));
    },
    changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => {
      // 勾选态看的是展示态: 权限组覆盖的权限也画成勾选, 再点一次就是"取消"。
      const shouldSelect = !selectedScopeKeysForPermission(permission, displaySelectionKeys(fields, catalogView))
        .includes(scopeKey);
      applySelectionChange(fields, catalogView, (current) =>
        nextPermissionScopeSelection(permission, scopeKey, shouldSelect, current),
      );
    },
    changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => {
      if (!scopeKey) {
        return;
      }
      const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) => permissionScopeSelectionKey(permission, scopeKey));

      applySelectionChange(fields, catalogView, (current) =>
        supportedPermissions.reduce(
          (selectionKeys, permission) =>
            shouldSelect
              ? nextPermissionScopeSelection(permission, scopeKey, true, selectionKeys)
              : nextPermissionScopeCascadeClearSelection(permission, scopeKey, selectionKeys),
          current,
        ),
      );
    },
  };
}

/** 展示态 = 直接勾选 ∪ 所选权限组覆盖的权限范围并集, 与 PermissionSelector 画出来的勾选一致。 */
function displaySelectionKeys(fields: AccessRequestFields, catalogView: CatalogView): string[] {
  return uniqueStrings([
    ...fields.selectedPermissionKeys,
    ...groupCoveredSelectionKeys(fields.authorizationGroupKeys, catalogView),
  ]);
}

/**
 * 直接权限选择变更的唯一入口。
 *
 * 变更先在展示态上算一遍: 如果它取消掉了所选权限组覆盖的权限范围, 说明用户正在改一份由权限组
 * 带来的权限。权限组是整体授予的, 少一项就不再是这个权限组, 因此必须把覆盖到它的那些权限组"落地"——
 * 把这些权限组从目标里摘掉, 把它们覆盖的其余权限转成直接申请, 再在这份基线上执行本次变更。
 * 没有覆盖到这一项的权限组保持选中。
 * 被落地的权限组覆盖但目录里不能单独申请的权限只能丢弃, 由提示文案明确告诉用户。
 */
function applySelectionChange(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  changeSelection: (selectionKeys: string[]) => string[],
): void {
  const groupKeys = fields.authorizationGroupKeys;
  const coveredKeys = groupCoveredSelectionKeys(groupKeys, catalogView);
  const nextDisplayKeys = changeSelection(displaySelectionKeys(fields, catalogView));
  const removedCoveredKeys = new Set(coveredKeys.filter((key) => !nextDisplayKeys.includes(key)));
  if (removedCoveredKeys.size === 0) {
    fields.setGroupMaterializationNoticeKey("");
    fields.setSelectedPermissionKeys((current) =>
      filterDirectGrantSelections(changeSelection(current), groupKeys, catalogView),
    );
    return;
  }

  const materializedGroupKeys = groupKeys.filter((groupKey) =>
    groupCoveredSelectionKeys([groupKey], catalogView).some((key) => removedCoveredKeys.has(key)),
  );
  const keptGroupKeys = groupKeys.filter((groupKey) => !materializedGroupKeys.includes(groupKey));
  const materializedCoveredKeys = groupCoveredSelectionKeys(materializedGroupKeys, catalogView);
  const requestableCoveredKeys = materializedCoveredKeys.filter((key) =>
    selectionIsDirectlyRequestable(key, catalogView),
  );
  fields.setAuthorizationGroupKeys(keptGroupKeys);
  fields.setSelectedPermissionKeys((current) =>
    filterDirectGrantSelections(
      changeSelection(uniqueStrings([...current, ...requestableCoveredKeys])),
      keptGroupKeys,
      catalogView,
    ),
  );
  fields.setGroupMaterializationNoticeKey(
    requestableCoveredKeys.length === materializedCoveredKeys.length
      ? "portal.request.groupMaterialized"
      : "portal.request.groupMaterializedPartially",
  );
}

/** 权限组可以覆盖当前用户在目录里看不到的权限范围, 那部分无法转成直接申请。 */
function selectionIsDirectlyRequestable(selectionKey: string, catalogView: CatalogView): boolean {
  const permission: ScopedPermissionItem | undefined =
    catalogView.permissionsByKey[directGrantSelectionPermissionKey(selectionKey)];
  const scopeKey = directGrantSelectionScopeKey(selectionKey);
  if (!permission || scopeKey === null) {
    return false;
  }
  return permissionScopeSelectionKey(permission, scopeKey) !== null;
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
