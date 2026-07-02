import type { PermissionGroupItem, PermissionItem } from "../../lib/domain";

export function collectPermissionKeys(groups: PermissionGroupItem[], ungroupedPermissions: PermissionItem[]): string[] {
  return [...collectPermissions(groups).map((permission) => permission.key), ...ungroupedPermissions.map((permission) => permission.key)];
}

export function collectPermissions(groups: PermissionGroupItem[]): PermissionItem[] {
  return groups.flatMap((group) => collectGroupPermissions(group));
}

export function collectGroupPermissions(group: PermissionGroupItem): PermissionItem[] {
  const permissionsByKey = new Map<string, PermissionItem>();
  for (const permission of directPermissionsForGroup(group)) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const childGroup of childGroupsForGroup(group)) {
    for (const permission of collectGroupPermissions(childGroup)) {
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
      permissions: (group.permissions ?? []).filter((permission) => !permission.app_key || permission.app_key === appKey),
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
    permissions: (group.permissions ?? []).filter((permission) => !permission.app_key || permission.app_key === appKey),
  };
}

export function filterPermissionByApp(permission: PermissionItem, appKey: string): PermissionItem | null {
  if (permission.app_key && permission.app_key !== appKey) {
    return null;
  }
  return permission;
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
