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
      // 先把权限组算出来: 多权限组授权在这里就抛错, 不留下半套草稿。
      const authorizationGroupKey = grant ? baseGrantAuthorizationGroupKey(grant) : "";
      fields.setBaseGrantId(grantId);
      fields.setBaseGrantRevision(grant?.grant_revision ?? null);
      if (!grant) {
        return;
      }
      fields.setAppKey(grant.app_key ?? "");
      fields.setAuthorizationGroupKey(authorizationGroupKey);
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

/**
 * 变更草稿只建模一个权限组, 而后端一条授权可以挂多个权限组
 * (走 GrantService 的入职、交接、控制台授权都会写 AccessGrantGroup)。
 * 这种授权若只取第一个权限组, 提交出去的变更会把其余权限组当成"要撤掉", 属于静默改写用户授权,
 * 因此直接失败。调用方(路由预填)负责在选中之前先给出可见错误。
 */
function baseGrantAuthorizationGroupKey(grant: PortalGrantRow): string {
  if (grant.groups.length > 1) {
    throw new Error(
      `基础授权 ${grant.grant_id} 含 ${grant.groups.length} 个权限组，申请表暂不支持多权限组变更。`,
    );
  }
  return grant.groups[0]?.key ?? "";
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
  fields.setGroupMaterializationNoticeKey("");
}

type PermissionSelectionActions = Pick<
  AccessRequestActions,
  "changeAuthorizationGroupKey" | "selectPermissionKeys" | "clearPermissionKeys" | "changePermissionScope" | "changePermissionGroupScope"
>;

function buildPermissionSelectionActions(fields: AccessRequestFields, catalogView: CatalogView): PermissionSelectionActions {
  return {
    changeAuthorizationGroupKey: (groupKey: string) => {
      fields.setAuthorizationGroupKey(groupKey);
      fields.setGroupMaterializationNoticeKey("");
      const coveredKeySet = groupCoveredSelectionKeySet(groupKey, catalogView);
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

/** 展示态 = 直接勾选 ∪ 所选权限组覆盖的权限范围, 与 PermissionSelector 画出来的勾选一致。 */
function displaySelectionKeys(fields: AccessRequestFields, catalogView: CatalogView): string[] {
  return uniqueStrings([
    ...fields.selectedPermissionKeys,
    ...groupCoveredSelectionKeys(fields.authorizationGroupKey, catalogView),
  ]);
}

/**
 * 直接权限选择变更的唯一入口。
 *
 * 变更先在展示态上算一遍: 如果它取消掉了所选权限组覆盖的权限范围, 说明用户正在改一份由权限组
 * 带来的权限。权限组是整体授予的, 少一项就不再是这个权限组, 因此必须把它"落地"——
 * 清空权限组目标, 把它覆盖的其余权限转成直接申请, 再在这份基线上执行本次变更。
 * 权限组覆盖但目录里不能单独申请的权限只能丢弃, 由提示文案明确告诉用户。
 */
function applySelectionChange(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  changeSelection: (selectionKeys: string[]) => string[],
): void {
  const groupKey = fields.authorizationGroupKey;
  const coveredKeys = groupCoveredSelectionKeys(groupKey, catalogView);
  const nextDisplayKeys = changeSelection(displaySelectionKeys(fields, catalogView));
  const removedCoveredKeys = coveredKeys.filter((key) => !nextDisplayKeys.includes(key));
  if (removedCoveredKeys.length === 0) {
    fields.setGroupMaterializationNoticeKey("");
    fields.setSelectedPermissionKeys((current) =>
      filterDirectGrantSelections(changeSelection(current), groupKey, catalogView),
    );
    return;
  }

  const requestableCoveredKeys = coveredKeys.filter((key) => selectionIsDirectlyRequestable(key, catalogView));
  fields.setAuthorizationGroupKey("");
  fields.setSelectedPermissionKeys((current) =>
    changeSelection(uniqueStrings([...current, ...requestableCoveredKeys])),
  );
  fields.setGroupMaterializationNoticeKey(
    requestableCoveredKeys.length === coveredKeys.length
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
