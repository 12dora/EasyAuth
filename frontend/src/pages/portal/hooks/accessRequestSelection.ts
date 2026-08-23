import type { ScopedPermissionItem } from "./accessRequestTypes";

export function directGrantSelectionKey(permissionKey: string, scopeKey: string): string {
  if (!permissionKey || !scopeKey) {
    throw new Error("直接权限选择的 permission key 和 scope key 不能为空");
  }
  return JSON.stringify([permissionKey, scopeKey]);
}

export function directGrantSelectionPermissionKey(selectionKey: string): string {
  return parseDirectGrantSelectionKey(selectionKey)[0];
}

export function directGrantSelectionScopeKey(selectionKey: string): string | null {
  return parseDirectGrantSelectionKey(selectionKey)[1];
}

function parseDirectGrantSelectionKey(selectionKey: string): readonly [string, string] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(selectionKey);
  } catch {
    throw new Error(`直接权限选择结构无效: ${selectionKey}`);
  }
  if (
    !Array.isArray(parsed)
    || parsed.length !== 2
    || typeof parsed[0] !== "string"
    || !parsed[0]
    || typeof parsed[1] !== "string"
    || !parsed[1]
  ) {
    throw new Error(`直接权限选择结构无效: ${selectionKey}`);
  }
  return [parsed[0], parsed[1]];
}

export function hasSelectionScope(selectionKey: string): boolean {
  return Boolean(directGrantSelectionScopeKey(selectionKey));
}

export function toggleListItem(items: string[], key: string): string[] {
  return items.includes(key) ? items.filter((item) => item !== key) : [...items, key];
}

export function uniqueStrings(items: string[]): string[] {
  return Array.from(new Set(items.filter(Boolean)));
}

export function listsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

function permissionSelectionKeys(permission: ScopedPermissionItem): string[] {
  return permissionScopeKeys(permission).map((scopeKey) => directGrantSelectionKey(permission.key, scopeKey));
}

export function permissionScopeSelectionKey(permission: ScopedPermissionItem, scopeKey: string): string | null {
  return (permission.scopes ?? []).some((scope) => scope.key === scopeKey)
    ? directGrantSelectionKey(permission.key, scopeKey)
    : null;
}

function permissionScopeKeys(permission: ScopedPermissionItem): string[] {
  const scopes = permission.scopes ?? [];
  return scopes.map((scope) => scope.key);
}

export function selectedScopeKeysForPermission(permission: ScopedPermissionItem, selectedPermissionKeys: string[]): string[] {
  const selectedKeySet = new Set(selectedPermissionKeys);
  return (permission.scopes ?? [])
    .filter((scope) => selectedKeySet.has(directGrantSelectionKey(permission.key, scope.key)))
    .map((scope) => scope.key);
}

export function nextPermissionScopeSelection(
  permission: ScopedPermissionItem,
  scopeKey: string,
  shouldSelect: boolean,
  selectedPermissionKeys: string[],
): string[] {
  const scopes = permission.scopes ?? [];
  const targetScopeIndex = scopes.findIndex((scope) => scope.key === scopeKey);
  if (targetScopeIndex === -1) {
    return selectedPermissionKeys;
  }
  const currentScopeKeys = selectedScopeKeysForPermission(permission, selectedPermissionKeys);
  const nextScopeKeys = shouldSelect
    ? scopes.slice(0, targetScopeIndex + 1).map((scope) => scope.key)
    : currentScopeKeys.filter((currentScopeKey) => {
        const currentScopeIndex = scopes.findIndex((scope) => scope.key === currentScopeKey);
        return currentScopeIndex !== -1 && currentScopeIndex < targetScopeIndex;
      });
  const permissionScopeKeySet = new Set(permissionSelectionKeys(permission));
  const otherSelectionKeys = selectedPermissionKeys.filter((selectionKey) => !permissionScopeKeySet.has(selectionKey));
  const nextPermissionSelectionKeys = nextScopeKeys
    .map((nextScopeKey) => permissionScopeSelectionKey(permission, nextScopeKey))
    .filter((selectionKey): selectionKey is string => Boolean(selectionKey));
  return uniqueStrings([...otherSelectionKeys, ...nextPermissionSelectionKeys]);
}

export function nextPermissionScopeCascadeClearSelection(
  permission: ScopedPermissionItem,
  scopeKey: string,
  selectedPermissionKeys: string[],
): string[] {
  const scopes = permission.scopes ?? [];
  const targetScopeIndex = scopes.findIndex((scope) => scope.key === scopeKey);
  if (targetScopeIndex === -1) {
    return selectedPermissionKeys;
  }
  const removableScopeKeys = new Set(scopes.slice(0, targetScopeIndex + 1).map((scope) => scope.key));
  const removableSelectionKeys = new Set(
    permissionSelectionKeys(permission).filter((selectionKey) => {
      const selectedScopeKey = directGrantSelectionScopeKey(selectionKey);
      return selectedScopeKey !== null && removableScopeKeys.has(selectedScopeKey);
    }),
  );
  return selectedPermissionKeys.filter((selectionKey) => !removableSelectionKeys.has(selectionKey));
}
