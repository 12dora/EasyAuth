import { ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";

import type { PermissionGroupItem, PermissionItem } from "../../../lib/domain";
import { collectGroupPermissions, isPermissionGroupItem } from "../permissionTree";

interface PermissionSelectorProps {
  appKey: string;
  groups: PermissionGroupItem[];
  ungroupedPermissions: PermissionItem[];
  selectedKeys: string[];
  expandedGroupKeys: string[];
  loading: boolean;
  errorMessage: string;
  onTogglePermission: (key: string) => void;
  onToggleGroup: (key: string) => void;
}

interface PermissionGroupRowsProps {
  group: PermissionGroupItem;
  depth: number;
  selectedKeys: string[];
  expandedGroupKeys: string[];
  onTogglePermission: (key: string) => void;
  onToggleGroup: (key: string) => void;
}

interface PermissionGroupHeaderProps {
  group: PermissionGroupItem;
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
  expandedGroupKeys,
  loading,
  errorMessage,
  onTogglePermission,
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
              expandedGroupKeys={expandedGroupKeys}
              onTogglePermission={onTogglePermission}
              onToggleGroup={onToggleGroup}
            />
          ))}
          {ungroupedPermissions.map((permission) => (
            <PermissionRow
              key={permission.key}
              permission={permission}
              depth={0}
              checked={selectedKeys.includes(permission.key)}
              onToggle={onTogglePermission}
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
  expandedGroupKeys,
  onTogglePermission,
  onToggleGroup,
}: PermissionGroupRowsProps) {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = collectGroupPermissions(group);
  const isExpanded = expandedGroupKeys.includes(group.key);
  const selectedCount = childPermissions.filter((permission) => selectedKeys.includes(permission.key)).length;

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
        onTogglePermission={onTogglePermission}
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
  onTogglePermission,
  onToggleGroup,
}: PermissionGroupRowsProps & { childGroups: PermissionGroupItem[]; isExpanded: boolean }) {
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
          checked={selectedKeys.includes(permission.key)}
          onToggle={onTogglePermission}
        />
      ))}
      {childGroups.map((childGroup) => (
        <PermissionGroupRows
          key={childGroup.key}
          group={childGroup}
          depth={depth + 1}
          selectedKeys={selectedKeys}
          expandedGroupKeys={expandedGroupKeys}
          onTogglePermission={onTogglePermission}
          onToggleGroup={onToggleGroup}
        />
      ))}
    </>
  );
}

function PermissionRow({
  permission,
  depth,
  checked,
  onToggle,
}: {
  permission: PermissionItem;
  depth: number;
  checked: boolean;
  onToggle: (key: string) => void;
}) {
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
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(permission.key)}
          aria-label={`选择 ${permission.key}`}
        />
      </td>
    </tr>
  );
}

function depthStyle(depth: number): CSSProperties {
  return { "--permission-depth": depth } as CSSProperties;
}
