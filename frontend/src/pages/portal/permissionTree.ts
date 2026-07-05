import type { PermissionGroupItem, PermissionItem } from "../../lib/domain";

/**
 * 权限-应用作用域判定的唯一口径(正本清源): 未选应用、权限无 app_key(应用无关权限),
 * 或权限 app_key 命中所选应用时都算匹配。分组与未分组路径共用此规则, 避免可见性漂移。
 */
export function permissionMatchesApp(permission: { app_key?: string }, appKey: string): boolean {
  return !appKey || !permission.app_key || permission.app_key === appKey;
}

export function collectPermissionKeys(groups: PermissionGroupItem[], ungroupedPermissions: PermissionItem[]): string[] {
  return [...collectPermissions(groups).map((permission) => permission.key), ...ungroupedPermissions.map((permission) => permission.key)];
}

export function collectPermissions(groups: PermissionGroupItem[]): PermissionItem[] {
  return groups.flatMap((group) => collectGroupPermissions(group));
}

export function collectGroupPermissions(group: PermissionGroupItem, visited: Set<string> = new Set()): PermissionItem[] {
  // 环形分组图(A⊂B⊂A)防御: 已访问过的分组直接短路, 避免无限递归 / 栈溢出。
  if (visited.has(group.key)) {
    return [];
  }
  visited.add(group.key);
  const permissionsByKey = new Map<string, PermissionItem>();
  for (const permission of directPermissionsForGroup(group)) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const childGroup of childGroupsForGroup(group)) {
    for (const permission of collectGroupPermissions(childGroup, visited)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values());
}

export function isPermissionGroupItem(item: PermissionGroupItem | PermissionItem): item is PermissionGroupItem {
  return "type" in item && item.type === "group";
}

export function filterGroupsByApp(groups: PermissionGroupItem[], appKey: string): PermissionGroupItem[] {
  if (!appKey) {
    return [];
  }
  return groups
    .filter((group) => !group.app_key || group.app_key === appKey)
    .map((group) => ({
      ...group,
      children: (group.children ?? [])
        .map((child) => (isPermissionGroupItem(child) ? filterGroupByApp(child, appKey) : filterPermissionByApp(child, appKey)))
        .filter((child): child is PermissionGroupItem | PermissionItem => Boolean(child)),
      permissions: (group.permissions ?? []).filter((permission) => permissionMatchesApp(permission, appKey)),
    }));
}

export function filterGroupByApp(group: PermissionGroupItem, appKey: string): PermissionGroupItem | null {
  if (group.app_key && group.app_key !== appKey) {
    return null;
  }
  return {
    ...group,
    children: (group.children ?? [])
      .map((child) => (isPermissionGroupItem(child) ? filterGroupByApp(child, appKey) : filterPermissionByApp(child, appKey)))
      .filter((child): child is PermissionGroupItem | PermissionItem => Boolean(child)),
    permissions: (group.permissions ?? []).filter((permission) => permissionMatchesApp(permission, appKey)),
  };
}

export function filterPermissionByApp(permission: PermissionItem, appKey: string): PermissionItem | null {
  return permissionMatchesApp(permission, appKey) ? permission : null;
}

function childGroupsForGroup(group: PermissionGroupItem): PermissionGroupItem[] {
  return (group.children ?? []).filter(isPermissionGroupItem);
}

function directPermissionsForGroup(group: PermissionGroupItem): PermissionItem[] {
  const permissionsByKey = new Map<string, PermissionItem>();
  for (const permission of group.permissions ?? []) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const child of group.children ?? []) {
    if (!isPermissionGroupItem(child)) {
      permissionsByKey.set(child.key, child);
    }
  }
  return Array.from(permissionsByKey.values());
}
