import { ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";

import { collectGroupPermissions, isPermissionGroupItem } from "../permissionTree";
import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
} from "../hooks/useAccessRequestForm";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/useAccessRequestForm";

interface PermissionSelectorProps {
  appKey: string;
  groups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  selectedKeys: string[];
  selectedScopes: Record<string, string>;
  expandedGroupKeys: string[];
  loading: boolean;
  errorMessage: string;
  onTogglePermission: (key: string) => void;
  onPermissionScopeChange: (permissionKey: string, scopeKey: string) => void;
  onToggleGroup: (key: string) => void;
}

interface PermissionGroupRowsProps {
  group: ScopedPermissionGroupItem;
  depth: number;
  selectedKeys: string[];
  selectedScopes: Record<string, string>;
  expandedGroupKeys: string[];
  onTogglePermission: (key: string) => void;
  onPermissionScopeChange: (permissionKey: string, scopeKey: string) => void;
  onToggleGroup: (key: string) => void;
}

interface PermissionGroupHeaderProps {
  group: ScopedPermissionGroupItem;
  depth: number;
  isExpanded: boolean;
  selectedCount: number;
  permissionCount: number;
  onToggleGroup: (key: string) => void;
}

export function PermissionSelector({
  appKey,
  groups,
  ungroupedPermissions,
  selectedKeys,
  selectedScopes,
  expandedGroupKeys,
  loading,
  errorMessage,
  onTogglePermission,
  onPermissionScopeChange,
  onToggleGroup,
}: PermissionSelectorProps) {
  if (!appKey) {
    return <div className="permission-selector-empty">选择应用后加载权限目录。</div>;
  }
  if (loading) {
    return <div className="permission-selector-empty">权限目录加载中。</div>;
  }
  if (errorMessage) {
    return <div className="permission-selector-empty">权限目录加载失败：{errorMessage}</div>;
  }

  return (
    <div className="permission-selector">
      <table className="permission-table" aria-label="权限选择">
        <thead>
          <tr>
            <th>权限</th>
            <th>Key</th>
            <th>Scope</th>
            <th>选择</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) => (
            <PermissionGroupRows
              key={group.key}
              group={group}
              depth={0}
              selectedKeys={selectedKeys}
              selectedScopes={selectedScopes}
              expandedGroupKeys={expandedGroupKeys}
              onTogglePermission={onTogglePermission}
              onPermissionScopeChange={onPermissionScopeChange}
              onToggleGroup={onToggleGroup}
            />
          ))}
          {ungroupedPermissions.map((permission) => (
            <PermissionRow
              key={permission.key}
              permission={permission}
              depth={0}
              selectedKeys={selectedKeys}
              checked={isPermissionSelected(permission.key, selectedKeys)}
              selectedScope={selectedScopes[permission.key] ?? ""}
              onToggle={onTogglePermission}
              onScopeChange={onPermissionScopeChange}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PermissionGroupRows({
  group,
  depth,
  selectedKeys,
  selectedScopes,
  expandedGroupKeys,
  onTogglePermission,
  onPermissionScopeChange,
  onToggleGroup,
}: PermissionGroupRowsProps) {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = collectGroupPermissions(group);
  const isExpanded = expandedGroupKeys.includes(group.key);
  const selectedCount = childPermissions.filter((permission) => isPermissionSelected(permission.key, selectedKeys)).length;

  return (
    <>
      <PermissionGroupHeader
        group={group}
        depth={depth}
        isExpanded={isExpanded}
        selectedCount={selectedCount}
        permissionCount={childPermissions.length}
        onToggleGroup={onToggleGroup}
      />
      <PermissionGroupChildren
        childGroups={childGroups}
        depth={depth}
        expandedGroupKeys={expandedGroupKeys}
        isExpanded={isExpanded}
        group={group}
        selectedKeys={selectedKeys}
        selectedScopes={selectedScopes}
        onTogglePermission={onTogglePermission}
        onPermissionScopeChange={onPermissionScopeChange}
        onToggleGroup={onToggleGroup}
      />
    </>
  );
}

function PermissionGroupHeader({
  group,
  depth,
  isExpanded,
  selectedCount,
  permissionCount,
  onToggleGroup,
}: PermissionGroupHeaderProps) {
  return (
    <tr className="permission-group-row">
      <td>
        <button
          type="button"
          className="permission-group-toggle"
          onClick={() => onToggleGroup(group.key)}
          aria-expanded={isExpanded}
          aria-label={`${isExpanded ? "收起" : "展开"} ${group.name}`}
          style={depthStyle(depth)}
        >
          <ChevronRight size={16} className={isExpanded ? "expanded" : ""} />
          <span className="permission-group-title">{group.name}</span>
          <span className="permission-group-count">
            {selectedCount}/{permissionCount}
          </span>
        </button>
      </td>
      <td>
        <code>{group.key}</code>
      </td>
      <td aria-label="权限组无 scope">-</td>
      <td aria-label="权限组不可直接选择">-</td>
    </tr>
  );
}

function PermissionGroupChildren({
  childGroups,
  depth,
  expandedGroupKeys,
  isExpanded,
  group,
  selectedKeys,
  selectedScopes,
  onTogglePermission,
  onPermissionScopeChange,
  onToggleGroup,
}: PermissionGroupRowsProps & { childGroups: ScopedPermissionGroupItem[]; isExpanded: boolean }) {
  if (!isExpanded) {
    return null;
  }

  return (
    <>
      {group.permissions?.map((permission) => (
        <PermissionRow
          key={permission.key}
          permission={permission}
          depth={depth + 1}
          selectedKeys={selectedKeys}
          checked={isPermissionSelected(permission.key, selectedKeys)}
          selectedScope={selectedScopes[permission.key] ?? ""}
          onToggle={onTogglePermission}
          onScopeChange={onPermissionScopeChange}
        />
      ))}
      {childGroups.map((childGroup) => (
        <PermissionGroupRows
          key={childGroup.key}
          group={childGroup}
          depth={depth + 1}
          selectedKeys={selectedKeys}
          selectedScopes={selectedScopes}
          expandedGroupKeys={expandedGroupKeys}
          onTogglePermission={onTogglePermission}
          onPermissionScopeChange={onPermissionScopeChange}
          onToggleGroup={onToggleGroup}
        />
      ))}
    </>
  );
}

function PermissionRow({
  permission,
  depth,
  selectedKeys,
  checked,
  selectedScope,
  onToggle,
  onScopeChange,
}: {
  permission: ScopedPermissionItem;
  depth: number;
  selectedKeys: string[];
  checked: boolean;
  selectedScope: string;
  onToggle: (key: string) => void;
  onScopeChange: (permissionKey: string, scopeKey: string) => void;
}) {
  const scopes = permission.scopes ?? [];
  const singleScope = scopes.length <= 1;
  const checkboxSelectionKey = singleScope ? permission.key : "";

  return (
    <tr className="permission-row">
      <td>
        <span className="permission-name" style={depthStyle(depth)}>
          {permission.name}
        </span>
      </td>
      <td>
        <code>{permission.key}</code>
      </td>
      <td>
        {singleScope ? (
          <select
            className="control"
            value={selectedScope}
            onChange={(event) => onScopeChange(permission.key, event.currentTarget.value)}
            aria-label={`${permission.key} scope`}
          >
            {scopes.length === 1 ? null : <option value="">选择 scope</option>}
            {scopes.map((scope) => (
              <option key={scope.key} value={scope.key}>
                {scope.name} ({scope.key})
              </option>
            ))}
          </select>
        ) : (
          <div className="inline-actions">
            {scopes.map((scope) => (
              <label key={scope.key} className="checkbox-label">
                <input
                  type="checkbox"
                  checked={selectedKeys.includes(directGrantSelectionKey(permission.key, scope.key))}
                  onChange={() => onToggle(directGrantSelectionKey(permission.key, scope.key))}
                  aria-label={`选择 ${permission.key} ${scope.key}`}
                />
                <span>
                  {scope.name} ({scope.key})
                </span>
              </label>
            ))}
          </div>
        )}
      </td>
      <td>
        {singleScope ? (
          <input
            type="checkbox"
            checked={checked}
            onChange={() => onToggle(checkboxSelectionKey)}
            aria-label={`选择 ${permission.key}`}
          />
        ) : (
          <span aria-label={`${permission.key} 多 scope 选择`}>-</span>
        )}
      </td>
    </tr>
  );
}

function depthStyle(depth: number): CSSProperties {
  return { "--permission-depth": depth } as CSSProperties;
}

function isPermissionSelected(permissionKey: string, selectedKeys: string[]): boolean {
  return selectedKeys.some((key) => directGrantSelectionPermissionKey(key) === permissionKey);
}
