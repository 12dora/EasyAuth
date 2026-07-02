import type { PermissionGroupItem, PermissionItem } from "../../lib/domain";

export function collectPermissionKeys(groups: PermissionGroupItem[], ungroupedPermissions: PermissionItem[]): string[] {
  return [...collectPermissions(groups).map((permission) => permission.key), ...ungroupedPermissions.map((permission) => permission.key)];
}

export function collectPermissions(groups: PermissionGroupItem[]): PermissionItem[] {
  return groups.flatMap((group) => collectGroupPermissions(group));
}

export function collectGroupPermissions(group: PermissionGroupItem): PermissionItem[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = (group.children ?? []).filter((child): child is PermissionItem => !isPermissionGroupItem(child));
  return [...(group.permissions ?? []), ...childPermissions, ...childGroups.flatMap((childGroup) => collectGroupPermissions(childGroup))];
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
