/*
 * 权限范围 chip 点一下会得到哪一份直接权限选择。
 *
 * 动作层(accessRequestActions)与界面上的禁用判定必须走同一条路径: 权限范围是递增关系,
 * 勾上一个范围会连同它以下的范围一起补齐(nextPermissionScopeSelection), 取消则连同它以上的范围
 * 一起清掉。只看被点的那一个范围键, 算不出这次点击真正会落下来的集合。
 */

import { collectScopedGroupPermissions } from "./accessRequestCatalog";
import {
  nextPermissionScopeCascadeClearSelection,
  nextPermissionScopeSelection,
  permissionScopeSelectionKey,
  selectedScopeKeysForPermission,
} from "./accessRequestSelection";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "./accessRequestTypes";

/** 权限行的范围 chip 点一下的方向: 展示态里已经勾着就是取消。 */
export function permissionScopeClickSelects(
  permission: ScopedPermissionItem,
  scopeKey: string,
  displaySelectedKeys: string[],
): boolean {
  return !selectedScopeKeysForPermission(permission, displaySelectedKeys).includes(scopeKey);
}

/** 权限行的范围 chip 点一下之后的选择集合。 */
export function nextSelectionForPermissionScopeClick(
  permission: ScopedPermissionItem,
  scopeKey: string,
  displaySelectedKeys: string[],
): string[] {
  return nextPermissionScopeSelection(
    permission,
    scopeKey,
    permissionScopeClickSelects(permission, scopeKey, displaySelectedKeys),
    displaySelectedKeys,
  );
}

/** 权限组表头的范围 chip 点一下之后的选择集合: 组内支持该范围的权限逐个走权限行同一条路径。 */
export function nextSelectionForGroupScopeClick(
  group: ScopedPermissionGroupItem,
  scopeKey: string,
  shouldSelect: boolean,
  displaySelectedKeys: string[],
): string[] {
  return collectScopedGroupPermissions(group)
    .filter((permission) => permissionScopeSelectionKey(permission, scopeKey))
    .reduce(
      (selectionKeys, permission) =>
        shouldSelect
          ? nextPermissionScopeSelection(permission, scopeKey, true, selectionKeys)
          : nextPermissionScopeCascadeClearSelection(permission, scopeKey, selectionKeys),
      displaySelectedKeys,
    );
}
