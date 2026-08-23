import { collectScopedGroupPermissions } from "../hooks/accessRequestCatalog";
import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
} from "../hooks/accessRequestSelection";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { isPermissionGroupItem } from "../permissionTree";

export type GroupSelectionState = "checked" | "indeterminate" | "unchecked";
export type ScopeOptionView = NonNullable<ScopedPermissionItem["scopes"]>[number];

export type PermissionSelectorRow =
  | {
      type: "group";
      id: string;
      group: ScopedPermissionGroupItem;
      depth: number;
      isExpanded: boolean;
      selectedCount: number;
      permissionCount: number;
      selectionState: GroupSelectionState;
      scopeOptions: ScopeOptionView[];
      isEntering: boolean;
      isExiting: boolean;
    }
  | {
      type: "permission";
      id: string;
      permission: ScopedPermissionItem;
      depth: number;
      isSelected: boolean;
      isEntering: boolean;
      isExiting: boolean;
    };

/** 递归建行时逐层共享的输入: 展开态、进出场动画键集与勾选态。 */
export interface PermissionRowContext {
  expandedGroupKeys: string[];
  enteringGroupKeys: string[];
  exitingGroupKeys: string[];
  selectedKeys: string[];
}

/** 祖先链累积的动画态: 子行整体跟随祖先进出场。 */
interface RowMotion {
  isEntering: boolean;
  isExiting: boolean;
}

const STATIC_MOTION: RowMotion = { isEntering: false, isExiting: false };

export function buildPermissionRows(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
  context: PermissionRowContext,
): PermissionSelectorRow[] {
  return [
    ...groups.flatMap((group) => buildGroupRows(group, 0, context, STATIC_MOTION)),
    ...ungroupedPermissions.map((permission) => permissionRow(permission, 0, context.selectedKeys, STATIC_MOTION)),
  ];
}

function buildGroupRows(
  group: ScopedPermissionGroupItem,
  depth: number,
  context: PermissionRowContext,
  ancestorMotion: RowMotion,
): PermissionSelectorRow[] {
  const isExpanded = context.expandedGroupKeys.includes(group.key);
  const isGroupExiting = context.exitingGroupKeys.includes(group.key);
  const childMotion: RowMotion = {
    isEntering: ancestorMotion.isEntering || context.enteringGroupKeys.includes(group.key),
    isExiting: ancestorMotion.isExiting || isGroupExiting,
  };
  const rows: PermissionSelectorRow[] = [groupRow(group, depth, isExpanded, context.selectedKeys, ancestorMotion)];

  const shouldRenderChildren = isExpanded || (isGroupExiting && !ancestorMotion.isEntering);

  if (!shouldRenderChildren) {
    return rows;
  }

  rows.push(
    ...directPermissionsForGroup(group).map((permission) =>
      permissionRow(permission, depth + 1, context.selectedKeys, childMotion),
    ),
    ...childGroupsForGroup(group).flatMap((childGroup) => buildGroupRows(childGroup, depth + 1, context, childMotion)),
  );

  return rows;
}

function groupRow(
  group: ScopedPermissionGroupItem,
  depth: number,
  isExpanded: boolean,
  selectedKeys: string[],
  motion: RowMotion,
): PermissionSelectorRow {
  const descendantPermissions = collectScopedGroupPermissions(group);
  return {
    type: "group",
    id: `group:${group.key}`,
    group,
    depth,
    isExpanded,
    selectedCount: descendantPermissions.filter((permission) => isPermissionSelected(permission.key, selectedKeys)).length,
    permissionCount: descendantPermissions.length,
    selectionState: groupSelectionState(group, selectedKeys),
    scopeOptions: groupScopeOptions(group),
    isEntering: motion.isEntering,
    isExiting: motion.isExiting,
  };
}

function permissionRow(
  permission: ScopedPermissionItem,
  depth: number,
  selectedKeys: string[],
  motion: RowMotion,
): PermissionSelectorRow {
  return {
    type: "permission",
    id: `permission:${permission.key}`,
    permission,
    depth,
    isSelected: isPermissionSelected(permission.key, selectedKeys),
    isEntering: motion.isEntering,
    isExiting: motion.isExiting,
  };
}

export function filterRowsToSelected(rows: PermissionSelectorRow[]): PermissionSelectorRow[] {
  return rows.filter((row) => rowMatchesSelected(row));
}

function rowMatchesSelected(row: PermissionSelectorRow): boolean {
  if (row.type === "group") {
    return row.selectionState !== "unchecked";
  }
  return row.isSelected;
}

function isPermissionSelected(permissionKey: string, selectedKeys: string[]): boolean {
  return selectedKeys.some((key) => directGrantSelectionPermissionKey(key) === permissionKey);
}

export function groupSelectionState(group: ScopedPermissionGroupItem, selectedKeys: string[]): GroupSelectionState {
  const selectionKeys = collectGroupSelectionKeys(group);
  if (selectionKeys.length === 0) {
    return "unchecked";
  }
  const selectedCount = selectionKeys.filter((key) => selectedKeys.includes(key)).length;
  if (selectedCount === 0) {
    return "unchecked";
  }
  return selectedCount === selectionKeys.length ? "checked" : "indeterminate";
}

function collectGroupSelectionKeys(group: ScopedPermissionGroupItem): string[] {
  return collectScopedGroupPermissions(group).flatMap((permission) => permissionSelectionKeys(permission));
}

function permissionSelectionKeys(permission: ScopedPermissionItem): string[] {
  const scopes = permission.scopes ?? [];
  return scopes.map((scope) => directGrantSelectionKey(permission.key, scope.key));
}

export function groupScopeSelectionState(
  group: ScopedPermissionGroupItem,
  scopeKey: string,
  selectedKeys: string[],
): GroupSelectionState {
  const supportedPermissions = collectScopedGroupPermissions(group).filter((permission) =>
    (permission.scopes ?? []).some((scope) => scope.key === scopeKey),
  );
  if (supportedPermissions.length === 0) {
    return "unchecked";
  }
  const selectedKeySet = new Set(selectedKeys);
  const exactSelectedCount = supportedPermissions.filter((permission) =>
    selectedKeySet.has(directGrantSelectionKey(permission.key, scopeKey)),
  ).length;
  if (exactSelectedCount === supportedPermissions.length) {
    return "checked";
  }
  if (exactSelectedCount > 0 || supportedPermissions.some((permission) => hasLowerScopeSelection(permission, scopeKey, selectedKeySet))) {
    return "indeterminate";
  }
  return "unchecked";
}

function hasLowerScopeSelection(permission: ScopedPermissionItem, scopeKey: string, selectedKeySet: Set<string>): boolean {
  const scopes = permission.scopes ?? [];
  const scopeIndex = scopes.findIndex((scope) => scope.key === scopeKey);
  if (scopeIndex <= 0) {
    return false;
  }
  return scopes.slice(0, scopeIndex).some((scope) => selectedKeySet.has(directGrantSelectionKey(permission.key, scope.key)));
}

function groupScopeOptions(group: ScopedPermissionGroupItem): ScopeOptionView[] {
  const scopesByKey = new Map<string, ScopeOptionView>();
  for (const permission of collectScopedGroupPermissions(group)) {
    for (const scope of permission.scopes ?? []) {
      if (!scopesByKey.has(scope.key)) {
        scopesByKey.set(scope.key, scope);
      }
    }
  }
  return Array.from(scopesByKey.values());
}

export function currentPageSelectionKeysFromRows(
  rows: Array<{ original: PermissionSelectorRow }>,
  scopeKey?: string,
): string[] {
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const row of rows) {
    if (row.original.type === "permission") {
      permissionsByKey.set(row.original.permission.key, row.original.permission);
      continue;
    }
    for (const permission of collectScopedGroupPermissions(row.original.group)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values()).flatMap((permission) =>
    scopeKey ? permissionSelectionKeysForScope(permission, scopeKey) : permissionSelectionKeys(permission),
  );
}

function permissionSelectionKeysForScope(permission: ScopedPermissionItem, scopeKey: string): string[] {
  return (permission.scopes ?? []).some((scope) => scope.key === scopeKey) ? [directGrantSelectionKey(permission.key, scopeKey)] : [];
}

export function currentPageGroupKeysFromRows(rows: Array<{ original: PermissionSelectorRow }>): string[] {
  return rows.map((row) => row.original).filter((row) => row.type === "group").map((row) => row.group.key);
}

function childGroupsForGroup(group: ScopedPermissionGroupItem): ScopedPermissionGroupItem[] {
  return (group.children ?? []).filter(isPermissionGroupItem);
}

function directPermissionsForGroup(group: ScopedPermissionGroupItem): ScopedPermissionItem[] {
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
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
