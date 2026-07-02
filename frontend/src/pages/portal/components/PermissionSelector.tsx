import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";
import { useMemo } from "react";
import { SelectInput } from "../../../components/Field";
import { EmptyState } from "../../../components/ui/EmptyState";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../components/ui/TablePrimitives";
import { TablePagination } from "../../../components/ui/TablePagination";

import { collectGroupPermissions, isPermissionGroupItem } from "../permissionTree";
import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
} from "../hooks/useAccessRequestForm";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/useAccessRequestForm";

const MONO_TEXT_CLASS = "font-mono text-[13px] leading-5 text-ink-soft";

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

type PermissionSelectorRow =
  | {
      type: "group";
      id: string;
      group: ScopedPermissionGroupItem;
      depth: number;
      isExpanded: boolean;
      selectedCount: number;
      permissionCount: number;
    }
  | {
      type: "permission";
      id: string;
      permission: ScopedPermissionItem;
      depth: number;
    };

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
  const rows = useMemo(
    () => buildPermissionRows(groups, ungroupedPermissions, expandedGroupKeys, selectedKeys),
    [expandedGroupKeys, groups, selectedKeys, ungroupedPermissions],
  );
  const columns = useMemo<ColumnDef<PermissionSelectorRow>[]>(
    () => [
      {
        id: "permission",
        header: "权限",
        cell: ({ row }) =>
          row.original.type === "group" ? (
            <PermissionGroupNameCell
              group={row.original.group}
              depth={row.original.depth}
              isExpanded={row.original.isExpanded}
              selectedCount={row.original.selectedCount}
              permissionCount={row.original.permissionCount}
              onToggleGroup={onToggleGroup}
            />
          ) : (
            <span className="block font-medium text-ink" style={depthStyle(row.original.depth)}>
              {row.original.permission.name}
            </span>
          ),
      },
      {
        id: "key",
        header: "权限 key",
        cell: ({ row }) => (
          <code className={MONO_TEXT_CLASS}>
            {row.original.type === "group" ? row.original.group.key : row.original.permission.key}
          </code>
        ),
      },
      {
        id: "scope",
        header: "scope",
        cell: ({ row }) =>
          row.original.type === "group" ? (
            <span aria-label="权限组无 scope">-</span>
          ) : (
            <PermissionScopeCell
              permission={row.original.permission}
              selectedKeys={selectedKeys}
              selectedScope={selectedScopes[row.original.permission.key] ?? ""}
              onToggle={onTogglePermission}
              onScopeChange={onPermissionScopeChange}
            />
          ),
      },
      {
        id: "selection",
        header: "选择",
        cell: ({ row }) =>
          row.original.type === "group" ? (
            <span aria-label="权限组不可直接选择">-</span>
          ) : (
            <PermissionSelectionCell
              permission={row.original.permission}
              checked={isPermissionSelected(row.original.permission.key, selectedKeys)}
              onToggle={onTogglePermission}
            />
          ),
      },
    ],
    [onPermissionScopeChange, onToggleGroup, onTogglePermission, selectedKeys, selectedScopes],
  );
  const table = useReactTable({
    data: rows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (row) => row.id,
  });

  if (!appKey) {
    return <EmptyState title="选择应用后加载权限目录" description="直接权限可留空，也可在应用目录加载后勾选具体权限。" />;
  }
  if (loading) {
    return <EmptyState title="权限目录加载中" description="正在读取可申请的直接权限。" />;
  }
  if (errorMessage) {
    return <EmptyState title="权限目录加载失败" description={errorMessage} />;
  }
  if (rows.length === 0) {
    return null;
  }

  return (
    <TableFrame>
      <TableRoot aria-label="权限选择">
        <TableHead>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHeaderCell
                  key={header.id}
                  className={header.column.id === "permission" ? "sticky left-0 z-20 bg-paper-deep/95" : undefined}
                >
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHeaderCell>
              ))}
            </TableRow>
          ))}
        </TableHead>
        <TableBody>
          {table.getRowModel().rows.length > 0 ? (
            table.getRowModel().rows.map((row) => (
              <TableRow key={row.id} className={row.original.type === "group" ? "bg-paper-deep/60 hover:bg-paper-deep" : undefined}>
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className={cell.column.id === "permission" ? "sticky left-0 z-10 bg-inherit" : undefined}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableEmptyRow colSpan={table.getAllLeafColumns().length}>
              <EmptyState title="暂无可选直接权限" description="当前应用未返回可直接申请的权限，可仅选择权限组发起申请。" />
            </TableEmptyRow>
          )}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} />
    </TableFrame>
  );
}

function PermissionGroupNameCell({
  group,
  depth,
  isExpanded,
  selectedCount,
  permissionCount,
  onToggleGroup,
}: {
  group: ScopedPermissionGroupItem;
  depth: number;
  isExpanded: boolean;
  selectedCount: number;
  permissionCount: number;
  onToggleGroup: (key: string) => void;
}) {
  return (
    <button
      type="button"
      className="inline-flex min-w-0 items-center gap-2 rounded-[2px] px-1.5 py-1 text-left text-[13px] font-semibold text-ink transition-colors hover:bg-ink/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--amber)_/_0.5)]"
      onClick={() => onToggleGroup(group.key)}
      aria-expanded={isExpanded}
      aria-label={`${isExpanded ? "收起" : "展开"} ${group.name}`}
      style={depthStyle(depth)}
    >
      <ChevronRight size={16} className={isExpanded ? "rotate-90 transition-transform" : "transition-transform"} />
      <span className="truncate">{group.name}</span>
      <span className="rounded-[2px] bg-paper px-1.5 py-0.5 font-mono text-[10.5px] font-medium leading-4 text-ink-soft">
        {selectedCount}/{permissionCount}
      </span>
    </button>
  );
}

function PermissionScopeCell({
  permission,
  selectedKeys,
  selectedScope,
  onToggle,
  onScopeChange,
}: {
  permission: ScopedPermissionItem;
  selectedKeys: string[];
  selectedScope: string;
  onToggle: (key: string) => void;
  onScopeChange: (permissionKey: string, scopeKey: string) => void;
}) {
  const scopes = permission.scopes ?? [];
  const singleScope = scopes.length <= 1;

  return (
    <>
      {singleScope ? (
        <SelectInput
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
        </SelectInput>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {scopes.map((scope) => (
            <label key={scope.key} className="inline-flex items-center gap-2 rounded-[2px] border border-[rgb(var(--hairline-strong))] bg-paper px-2.5 py-1.5 text-[13px] text-ink-soft">
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
    </>
  );
}

function PermissionSelectionCell({
  permission,
  checked,
  onToggle,
}: {
  permission: ScopedPermissionItem;
  checked: boolean;
  onToggle: (key: string) => void;
}) {
  const singleScope = (permission.scopes ?? []).length <= 1;

  return (
    <>
      {singleScope ? (
        <input
          type="checkbox"
          checked={checked}
          onChange={() => onToggle(permission.key)}
          aria-label={`选择 ${permission.key}`}
        />
      ) : (
        <span aria-label={`${permission.key} 多 scope 选择`}>-</span>
      )}
    </>
  );
}

function buildPermissionRows(
  groups: ScopedPermissionGroupItem[],
  ungroupedPermissions: ScopedPermissionItem[],
  expandedGroupKeys: string[],
  selectedKeys: string[],
): PermissionSelectorRow[] {
  return [
    ...groups.flatMap((group) => buildGroupRows(group, 0, expandedGroupKeys, selectedKeys)),
    ...ungroupedPermissions.map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: 0,
    })),
  ];
}

function buildGroupRows(
  group: ScopedPermissionGroupItem,
  depth: number,
  expandedGroupKeys: string[],
  selectedKeys: string[],
): PermissionSelectorRow[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = collectGroupPermissions(group);
  const isExpanded = expandedGroupKeys.includes(group.key);
  const rows: PermissionSelectorRow[] = [
    {
      type: "group",
      id: `group:${group.key}`,
      group,
      depth,
      isExpanded,
      selectedCount: childPermissions.filter((permission) => isPermissionSelected(permission.key, selectedKeys)).length,
      permissionCount: childPermissions.length,
    },
  ];

  if (!isExpanded) {
    return rows;
  }

  rows.push(
    ...(group.permissions ?? []).map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: depth + 1,
    })),
    ...childGroups.flatMap((childGroup) => buildGroupRows(childGroup, depth + 1, expandedGroupKeys, selectedKeys)),
  );

  return rows;
}

function depthStyle(depth: number): CSSProperties {
  return { "--permission-depth": depth } as CSSProperties;
}

function isPermissionSelected(permissionKey: string, selectedKeys: string[]): boolean {
  return selectedKeys.some((key) => directGrantSelectionPermissionKey(key) === permissionKey);
}
