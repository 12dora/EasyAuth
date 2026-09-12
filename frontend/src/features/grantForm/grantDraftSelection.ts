/**
 * 授权草稿的目标选择变更。
 *
 * 与门户申请共用同一套纯函数(accessRequestSelection / accessRequestCatalog / accessRequestScopeClick),
 * 因此权限范围的级联、授权组覆盖的展示态、以及"取消组内某一项就把授权组落地成逐项直接权限"的语义
 * 与门户完全一致。这里只去掉门户特有的撤销/续期约束——管理员授权没有基础授权可减。
 */

import {
  filterDirectGrantSelections,
  groupCoveredSelectionKeys,
  groupCoveredSelectionKeySet,
} from "../../pages/portal/hooks/accessRequestCatalog";
import {
  directGrantSelectionPermissionKey,
  directGrantSelectionScopeKey,
  permissionScopeSelectionKey,
  uniqueStrings,
} from "../../pages/portal/hooks/accessRequestSelection";
import type { CatalogView, ScopedPermissionItem } from "../../pages/portal/hooks/accessRequestTypes";
import type { GrantDraft } from "./grantDraft";

/** 展示态 = 直接勾选 ∪ 所选授权组覆盖的权限范围, 与 PermissionSelector 画出来的勾选一致。 */
export function grantDisplaySelectionKeys(draft: GrantDraft, catalogView: CatalogView): string[] {
  return uniqueStrings([
    ...draft.selectedPermissionKeys,
    ...groupCoveredSelectionKeys(draft.authorizationGroupKeys, catalogView),
  ]);
}

/**
 * 从草稿里摘掉组织授权锁定的目标。
 *
 * 锁定组覆盖的权限范围也要丢掉: 回填时本人来源的直接权限可能正好落在组织组的覆盖里,
 * 不摘的话提交会把组织授权再抄一份成个人授权。
 */
export function grantDraftExcludingLockedKeys(
  draft: GrantDraft,
  lockedGroupKeys: string[],
  lockedPermissionKeys: string[],
  catalogView: CatalogView,
): GrantDraft {
  const lockedGroupKeySet = new Set(lockedGroupKeys);
  const lockedSelectionKeySet = new Set([
    ...lockedPermissionKeys,
    ...groupCoveredSelectionKeys(lockedGroupKeys, catalogView),
  ]);
  return {
    ...draft,
    authorizationGroupKeys: draft.authorizationGroupKeys.filter((key) => !lockedGroupKeySet.has(key)),
    selectedPermissionKeys: draft.selectedPermissionKeys.filter((key) => !lockedSelectionKeySet.has(key)),
  };
}

/**
 * 换被授权人会作废整张草稿的"现状"部分: 目标与期限描述的是上一个人的授权, 换人后一条都不成立。
 * 说明保留 —— 管理员多半是在给同一批人办同一件事。
 */
export function grantDraftWithoutGrantee(draft: GrantDraft): GrantDraft {
  return {
    ...draft,
    authorizationGroupKeys: [],
    selectedPermissionKeys: [],
    grantType: "permanent",
    expiresAt: "",
    expiresAtSource: "",
  };
}

/** 换应用会作废整张目标草稿: 授权组、直接权限一并清空(期限与说明保留)。 */
export function grantDraftWithAppKey(draft: GrantDraft, appKey: string): GrantDraft {
  return { ...draft, appKey, authorizationGroupKeys: [], selectedPermissionKeys: [] };
}

/** 选中授权组后, 被它覆盖的直接权限不再单独提交(后端按组存组)。 */
export function grantDraftWithAuthorizationGroupKeys(
  draft: GrantDraft,
  groupKeys: string[],
  catalogView: CatalogView,
): GrantDraft {
  const nextGroupKeys = uniqueStrings(groupKeys);
  const coveredKeySet = groupCoveredSelectionKeySet(nextGroupKeys, catalogView);
  return {
    ...draft,
    authorizationGroupKeys: nextGroupKeys,
    selectedPermissionKeys: draft.selectedPermissionKeys.filter((key) => !coveredKeySet.has(key)),
  };
}

/**
 * 直接权限选择变更的唯一入口。
 *
 * 变更先在展示态上算一遍: 如果它取消掉了所选授权组覆盖的权限范围, 说明用户在改一份由授权组带来的
 * 权限。授权组是整体授予的, 少一项就不再是这个授权组, 因此把覆盖到它的授权组"落地"——从目标里摘掉
 * 该授权组, 把它覆盖的其余权限转成直接权限, 再在这份基线上执行本次变更。
 * 授权组可以覆盖目录里不存在的权限范围, 那部分无法落地成直接权限, 只能丢弃。
 */
export function grantDraftWithSelectionChange(
  draft: GrantDraft,
  catalogView: CatalogView,
  changeSelection: (selectionKeys: string[]) => string[],
): GrantDraft {
  const groupKeys = draft.authorizationGroupKeys;
  const coveredKeys = groupCoveredSelectionKeys(groupKeys, catalogView);
  const nextDisplayKeys = changeSelection(grantDisplaySelectionKeys(draft, catalogView));
  const removedCoveredKeys = new Set(coveredKeys.filter((key) => !nextDisplayKeys.includes(key)));
  if (removedCoveredKeys.size === 0) {
    return {
      ...draft,
      selectedPermissionKeys: filterDirectGrantSelections(
        changeSelection(draft.selectedPermissionKeys),
        groupKeys,
        catalogView,
      ),
    };
  }

  const materializedGroupKeys = groupKeys.filter((groupKey) =>
    groupCoveredSelectionKeys([groupKey], catalogView).some((key) => removedCoveredKeys.has(key)),
  );
  const keptGroupKeys = groupKeys.filter((groupKey) => !materializedGroupKeys.includes(groupKey));
  const grantableCoveredKeys = groupCoveredSelectionKeys(materializedGroupKeys, catalogView).filter((key) =>
    selectionIsInCatalog(key, catalogView),
  );
  return {
    ...draft,
    authorizationGroupKeys: keptGroupKeys,
    selectedPermissionKeys: filterDirectGrantSelections(
      changeSelection(uniqueStrings([...draft.selectedPermissionKeys, ...grantableCoveredKeys])),
      keptGroupKeys,
      catalogView,
    ),
  };
}

function selectionIsInCatalog(selectionKey: string, catalogView: CatalogView): boolean {
  const permission: ScopedPermissionItem | undefined =
    catalogView.permissionsByKey[directGrantSelectionPermissionKey(selectionKey)];
  const scopeKey = directGrantSelectionScopeKey(selectionKey);
  if (!permission || scopeKey === null) {
    return false;
  }
  return permissionScopeSelectionKey(permission, scopeKey) !== null;
}
