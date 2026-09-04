import type { PortalGrantRow } from "../portalListPayload";
import {
  descendantGroupKeys,
  filterDirectGrantSelections,
  groupCoveredSelectionKeys,
  groupCoveredSelectionKeySet,
} from "./accessRequestCatalog";
import {
  nextSelectionForGroupScopeClick,
  permissionScopeClickSelects,
} from "./accessRequestScopeClick";
import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
  directGrantSelectionScopeKey,
  nextPermissionScopeSelection,
  permissionScopeSelectionKey,
  toggleListItem,
  uniqueStrings,
} from "./accessRequestSelection";
import {
  addedSelectionKeysOutsideRetainableTarget,
  retainableSelectionKeySet,
  revokeBaseGrantSnapshot,
  type RevokeBaseGrantSnapshot,
} from "./accessRequestTargetLock";
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
  const revokeSnapshot = revokeBaseGrantSnapshot(
    fields.requestType,
    currentGrants.find((item) => String(item.grant_id) === fields.baseGrantId),
  );
  return {
    ...buildTargetActions(fields, currentGrants),
    ...buildPermissionSelectionActions(fields, catalogView, revokeSnapshot),
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

function buildPermissionSelectionActions(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  revokeSnapshot: RevokeBaseGrantSnapshot | null,
): PermissionSelectionActions {
  return {
    changeAuthorizationGroupKeys: (groupKeys: string[]) => {
      assertTargetIsEditable(fields.requestType);
      const nextGroupKeys = uniqueStrings(groupKeys);
      assertRevokeKeepsGroupsWithinBaseGrant(nextGroupKeys, revokeSnapshot);
      fields.setAuthorizationGroupKeys(nextGroupKeys);
      fields.setGroupMaterializationNoticeKey("");
      const coveredKeySet = groupCoveredSelectionKeySet(nextGroupKeys, catalogView);
      fields.setSelectedPermissionKeys((current) => current.filter((key) => !coveredKeySet.has(key)));
    },
    selectPermissionKeys: (keys: string[]) => {
      applySelectionChange(fields, catalogView, revokeSnapshot, (current) => uniqueStrings([...current, ...keys]));
    },
    clearPermissionKeys: (keys: string[]) => {
      const keySet = new Set(keys);
      applySelectionChange(fields, catalogView, revokeSnapshot, (current) => current.filter((key) => !keySet.has(key)));
    },
    changePermissionScope: (permission: ScopedPermissionItem, scopeKey: string) => {
      // 勾选态看的是展示态: 权限组覆盖的权限也画成勾选, 再点一次就是"取消"。方向只按展示态定一次,
      // 后面对直接权限集合重放同一次变更时不能再算一遍, 否则被权限组覆盖的项会反向变成"选中"。
      const shouldSelect = permissionScopeClickSelects(permission, scopeKey, displaySelectionKeys(fields, catalogView));
      applySelectionChange(fields, catalogView, revokeSnapshot, (current) =>
        nextPermissionScopeSelection(permission, scopeKey, shouldSelect, current),
      );
    },
    changePermissionGroupScope: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => {
      if (!scopeKey) {
        return;
      }
      applySelectionChange(fields, catalogView, revokeSnapshot, (current) =>
        nextSelectionForGroupScopeClick(group, scopeKey, shouldSelect, current),
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
 *
 * 只有 grant / change 能这样落地: renew 完全不能改目标, revoke 只能整组摘掉,
 * 见 assertTargetIsEditable 与下面撤销分支的注释。
 */
function applySelectionChange(
  fields: AccessRequestFields,
  catalogView: CatalogView,
  revokeSnapshot: RevokeBaseGrantSnapshot | null,
  changeSelection: (selectionKeys: string[]) => string[],
): void {
  assertTargetIsEditable(fields.requestType);
  const groupKeys = fields.authorizationGroupKeys;
  const coveredKeys = groupCoveredSelectionKeys(groupKeys, catalogView);
  const currentDisplayKeys = displaySelectionKeys(fields, catalogView);
  const nextDisplayKeys = changeSelection(currentDisplayKeys);
  assertRevokeKeepsSelectionWithinBaseGrant(currentDisplayKeys, nextDisplayKeys, revokeSnapshot, coveredKeys);
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
  if (fields.requestType === "revoke") {
    // 撤销申请提交的目标是"撤销之后保留下来的授权"(application_grants._apply_revoke_request 直接
    // 拿它当新的成员关系), 后端要求它是基础授权的子集(submission_validation._validate_revoke_subset)。
    // 把权限组落地成逐项直接申请会引入基础授权里没有的直接权限, 必然被拒, 所以撤销只能整组摘掉:
    // 取消权限组覆盖的任一权限 = 该权限组整体不再保留。
    fields.setAuthorizationGroupKeys(keptGroupKeys);
    fields.setSelectedPermissionKeys((current) =>
      filterDirectGrantSelections(changeSelection(current), keptGroupKeys, catalogView),
    );
    fields.setGroupMaterializationNoticeKey("portal.request.groupRevokedWhole");
    return;
  }

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

/**
 * 续期的目标必须与基础授权一模一样(submission_validation._validate_renew_targets: 权限组集合与
 * 直接权限集合都要求相等), 所以整个申请目标不可编辑。界面上目标选择器对 renew 是只读的,
 * 走到这里说明接线出了问题, 直接失败而不是悄悄改出一份必被后端拒绝的草稿。
 */
function assertTargetIsEditable(requestType: AccessRequestType): void {
  if (requestType === "renew") {
    throw new Error("续期申请不能修改申请目标：续期目标必须与基础授权完全一致。");
  }
}

/*
 * 撤销的目标只能从基础授权往下减(submission_validation._validate_revoke_subset), 加入基础授权里
 * 没有的权限组或直接权限必然被后端拒绝。界面已经把越界的勾选框与 chip 全部禁用, 走到下面两个断言
 * 说明接线出了问题, 与续期的守卫一样直接失败, 不造一份必被拒绝的草稿。
 */

function assertRevokeKeepsGroupsWithinBaseGrant(
  nextGroupKeys: string[],
  revokeSnapshot: RevokeBaseGrantSnapshot | null,
): void {
  if (revokeSnapshot === null) {
    return;
  }
  const addedGroupKeys = nextGroupKeys.filter((key) => !revokeSnapshot.groupKeys.includes(key));
  if (addedGroupKeys.length > 0) {
    throw new Error(`撤销申请不能添加基础授权之外的权限组：${addedGroupKeys.join(", ")}`);
  }
}

function assertRevokeKeepsSelectionWithinBaseGrant(
  currentDisplayKeys: string[],
  nextDisplayKeys: string[],
  revokeSnapshot: RevokeBaseGrantSnapshot | null,
  coveredKeys: string[],
): void {
  if (revokeSnapshot === null) {
    return;
  }
  const outsideKeys = addedSelectionKeysOutsideRetainableTarget(
    currentDisplayKeys,
    nextDisplayKeys,
    retainableSelectionKeySet(revokeSnapshot, coveredKeys),
  );
  if (outsideKeys.length > 0) {
    throw new Error(`撤销申请不能添加基础授权之外的权限：${outsideKeys.join(", ")}`);
  }
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
