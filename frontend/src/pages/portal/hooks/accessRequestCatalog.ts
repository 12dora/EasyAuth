import { collectPermissionKeys, filterGroupsByApp, permissionMatchesApp } from "../permissionTree";
import { directGrantSelectionKey, uniqueStrings } from "./accessRequestSelection";
import type {
  CatalogView,
  PortalRequestCatalogView,
  ScopeOption,
  ScopedPermissionGroupItem,
  ScopedPermissionItem,
} from "./accessRequestTypes";

export function buildCatalogView(catalog: PortalRequestCatalogView | undefined, appKey: string, currentUserId: string): CatalogView {
  const permissionGroups = filterGroupsByApp(catalog?.permission_groups ?? [], appKey);
  // FF-12: 未分组权限沿用与分组一致的应用作用域判定, 保持应用无关权限在两条路径下同样可见。
  const ungroupedPermissions = (catalog?.ungrouped_permissions ?? []).filter((permission) =>
    permissionMatchesApp(permission, appKey),
  );
  const scopesByPermissionKey = buildScopesByPermissionKey(permissionGroups, ungroupedPermissions);
  const permissionsByKey = buildPermissionsByKey(permissionGroups, ungroupedPermissions);

  return {
    apps: catalog?.apps ?? [],
    // FF-7: 申请人不得自选为审批人; 前端从候选中剔除自己(服务端仍是权威校验)。
    approverOptions: (catalog?.approver_options ?? []).filter((option) => option.user_id !== currentUserId),
    authorizationGroups: (catalog?.authorization_groups ?? []).filter((group) => !appKey || group.app_key === appKey),
    permissionGroups,
    ungroupedPermissions,
    visiblePermissionKeys: collectPermissionKeys(permissionGroups, ungroupedPermissions),
    scopesByPermissionKey,
    permissionsByKey,
  };
}

/** 权限只有唯一范围时自动选中它, 并丢弃目录里已不存在的历史范围选择。 */
export function nextDefaultPermissionScopes(
  current: Record<string, string>,
  visiblePermissionKeys: string[],
  scopesByPermissionKey: Record<string, ScopeOption[]>,
): Record<string, string> {
  const next: Record<string, string> = {};
  let changed = false;
  for (const permissionKey of visiblePermissionKeys) {
    const scopes = scopesByPermissionKey[permissionKey] ?? [];
    const currentScope = current[permissionKey];
    if (currentScope && scopes.some((scope) => scope.key === currentScope)) {
      next[permissionKey] = currentScope;
      continue;
    }
    if (scopes.length === 1) {
      next[permissionKey] = scopes[0].key;
      changed = true;
    } else if (currentScope) {
      changed = true;
    }
  }
  return changed || Object.keys(current).length !== Object.keys(next).length ? next : current;
}

/** 一条授权可以挂多个权限组, 覆盖范围按并集算(顺序按 groupKeys 给定的顺序去重)。 */
export function groupCoveredSelectionKeys(groupKeys: string[], catalogView: CatalogView): string[] {
  return uniqueStrings(
    groupKeys.flatMap((groupKey) => {
      const group = catalogView.authorizationGroups.find((item) => item.key === groupKey);
      return (group?.grants ?? []).map((grant) => directGrantSelectionKey(grant.permission_key, grant.scope_key));
    }),
  );
}

export function groupCoveredSelectionKeySet(groupKeys: string[], catalogView: CatalogView): Set<string> {
  return new Set(groupCoveredSelectionKeys(groupKeys, catalogView));
}

export function filterDirectGrantSelections(
  selectionKeys: string[],
  groupKeys: string[],
  catalogView: CatalogView,
): string[] {
  const coveredKeySet = groupCoveredSelectionKeySet(groupKeys, catalogView);
  return uniqueStrings(selectionKeys)
    .filter((key) => !coveredKeySet.has(key));
}

export function collectScopedGroupPermissions(group: ScopedPermissionGroupItem, visited: Set<string> = new Set()): ScopedPermissionItem[] {
  // 环形分组图防御: 已访问过的分组短路, 避免无限递归。
  if (visited.has(group.key)) {
    return [];
  }
  visited.add(group.key);
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const permission of directPermissionsForGroup(group)) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const childGroup of childGroupsForGroup(group)) {
    for (const permission of collectScopedGroupPermissions(childGroup, visited)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values());
}

export function descendantGroupKeys(groups: ScopedPermissionGroupItem[], groupKey: string): string[] {
  const group = findPermissionGroup(groups, groupKey);
  return group ? collectDescendantGroupKeys(group) : [];
}

function findPermissionGroup(
  groups: ScopedPermissionGroupItem[],
  groupKey: string,
  visited: Set<string> = new Set(),
): ScopedPermissionGroupItem | null {
  for (const group of groups) {
    if (group.key === groupKey) {
      return group;
    }
    // 环形分组图防御: 不重复进入已访问分组。
    if (visited.has(group.key)) {
      continue;
    }
    visited.add(group.key);
    const childResult = findPermissionGroup(childGroupsForGroup(group), groupKey, visited);
    if (childResult) {
      return childResult;
    }
  }
  return null;
}

function collectDescendantGroupKeys(group: ScopedPermissionGroupItem, visited: Set<string> = new Set()): string[] {
  // 环形分组图防御: 已访问过的分组短路, 避免无限递归。
  if (visited.has(group.key)) {
    return [];
  }
  visited.add(group.key);
  const childGroups = childGroupsForGroup(group);
  return childGroups.flatMap((childGroup) => [childGroup.key, ...collectDescendantGroupKeys(childGroup, visited)]);
}

function buildScopesByPermissionKey(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
): Record<string, ScopeOption[]> {
  const permissions = [...collectScopedPermissions(groups), ...ungroupedPermissions];
  return Object.fromEntries(permissions.map((permission) => [permission.key, permission.scopes ?? []]));
}

function buildPermissionsByKey(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
): Record<string, ScopedPermissionItem> {
  const permissions = [...collectScopedPermissions(groups), ...ungroupedPermissions];
  return Object.fromEntries(permissions.map((permission) => [permission.key, permission]));
}

function collectScopedPermissions(groups: ScopedPermissionGroupItem[]): ScopedPermissionItem[] {
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const group of groups) {
    for (const permission of collectScopedGroupPermissions(group)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values());
}

function childGroupsForGroup(group: ScopedPermissionGroupItem): ScopedPermissionGroupItem[] {
  return (group.children ?? []).filter(
    (child): child is ScopedPermissionGroupItem => "type" in child && child.type === "group",
  );
}

function directPermissionsForGroup(group: ScopedPermissionGroupItem): ScopedPermissionItem[] {
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const permission of group.permissions ?? []) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const child of group.children ?? []) {
    if (!("type" in child) || child.type !== "group") {
      permissionsByKey.set(child.key, child);
    }
  }
  return Array.from(permissionsByKey.values());
}
