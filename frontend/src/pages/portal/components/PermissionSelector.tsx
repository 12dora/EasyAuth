import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { SelectInput } from "../../../components/Field";
import { EmptyState } from "../../../components/ui/EmptyState";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../components/ui/TablePrimitives";
import { TablePagination } from "../../../components/ui/TablePagination";

import { isPermissionGroupItem } from "../permissionTree";
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
  onTogglePermissionGroup: (group: ScopedPermissionGroupItem, shouldSelect: boolean) => void;
  onPermissionScopeChange: (permissionKey: string, scopeKey: string) => void;
  onPermissionGroupScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string) => void;
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
      selectionState: GroupSelectionState;
      scopeOptions: string[];
      isExiting: boolean;
    }
  | {
      type: "permission";
      id: string;
      permission: ScopedPermissionItem;
      depth: number;
      isExiting: boolean;
    };

type GroupSelectionState = "checked" | "indeterminate" | "unchecked";

const EXIT_ANIMATION_MS = 160;

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
  onTogglePermissionGroup,
  onPermissionScopeChange,
  onPermissionGroupScopeChange,
  onToggleGroup,
}: PermissionSelectorProps) {
  const exitingGroupKeys = useExitingGroupKeys(expandedGroupKeys);
  const rows = useMemo(
    () => buildPermissionRows(groups, ungroupedPermissions, expandedGroupKeys, exitingGroupKeys, selectedKeys),
    [expandedGroupKeys, exitingGroupKeys, groups, selectedKeys, ungroupedPermissions],
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
            <span className="permission-selector__permission-name block font-medium text-ink" style={depthStyle(row.original.depth)}>
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
            <PermissionGroupScopeCell
              group={row.original.group}
              scopeOptions={row.original.scopeOptions}
              onScopeChange={onPermissionGroupScopeChange}
            />
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
            <PermissionGroupSelectionCell
              group={row.original.group}
              selectionState={row.original.selectionState}
              onToggleGroup={onTogglePermissionGroup}
            />
          ) : (
            <PermissionSelectionCell
              permission={row.original.permission}
              checked={isPermissionSelected(row.original.permission.key, selectedKeys)}
              onToggle={onTogglePermission}
            />
          ),
      },
    ],
    [onPermissionGroupScopeChange, onPermissionScopeChange, onToggleGroup, onTogglePermission, onTogglePermissionGroup, selectedKeys, selectedScopes],
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
              <TableRow
                key={row.id}
                className={joinClassNames(
                  "permission-selector__row",
                  row.original.type === "group" && "permission-selector__row--group bg-paper-deep/60 hover:bg-paper-deep",
                  row.original.isExiting && "permission-selector__row--exiting",
                )}
                onClick={groupRowClickHandler(row.original, onToggleGroup)}
              >
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
      className="permission-selector__group-button inline-flex min-w-0 items-center gap-2 rounded-[2px] px-1.5 py-1 text-left text-[13px] font-semibold text-ink transition-colors hover:bg-ink/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[rgb(var(--amber)_/_0.5)]"
      onClick={(event) => {
        event.stopPropagation();
        onToggleGroup(group.key);
      }}
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

function PermissionGroupScopeCell({
  group,
  scopeOptions,
  onScopeChange,
}: {
  group: ScopedPermissionGroupItem;
  scopeOptions: string[];
  onScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string) => void;
}) {
  if (scopeOptions.length === 0) {
    return <span aria-label="权限组无 scope">-</span>;
  }

  return (
    <SelectInput
      value=""
      onClick={(event) => event.stopPropagation()}
      onChange={(event) => onScopeChange(group, event.currentTarget.value)}
      aria-label={`${group.key} 权限组 scope`}
    >
      <option value="">批量 scope</option>
      {scopeOptions.map((scopeKey) => (
        <option key={scopeKey} value={scopeKey}>
          {scopeKey}
        </option>
      ))}
    </SelectInput>
  );
}

function PermissionGroupSelectionCell({
  group,
  selectionState,
  onToggleGroup,
}: {
  group: ScopedPermissionGroupItem;
  selectionState: GroupSelectionState;
  onToggleGroup: (group: ScopedPermissionGroupItem, shouldSelect: boolean) => void;
}) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = selectionState === "indeterminate";
    }
  }, [selectionState]);

  return (
    <input
      ref={checkboxRef}
      type="checkbox"
      checked={selectionState === "checked"}
      onClick={(event) => event.stopPropagation()}
      onChange={() => onToggleGroup(group, selectionState !== "checked")}
      aria-label={`选择权限组 ${group.key}`}
    />
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
          onClick={(event) => event.stopPropagation()}
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
                onClick={(event) => event.stopPropagation()}
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
          onClick={(event) => event.stopPropagation()}
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
  exitingGroupKeys: string[],
  selectedKeys: string[],
): PermissionSelectorRow[] {
  return [
    ...groups.flatMap((group) => buildGroupRows(group, 0, expandedGroupKeys, exitingGroupKeys, selectedKeys, false)),
    ...ungroupedPermissions.map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: 0,
      isExiting: false,
    })),
  ];
}

function buildGroupRows(
  group: ScopedPermissionGroupItem,
  depth: number,
  expandedGroupKeys: string[],
  exitingGroupKeys: string[],
  selectedKeys: string[],
  isAncestorExiting: boolean,
): PermissionSelectorRow[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = collectScopedGroupPermissions(group);
  const isExpanded = expandedGroupKeys.includes(group.key);
  const isGroupExiting = exitingGroupKeys.includes(group.key);
  const isChildExiting = isAncestorExiting || isGroupExiting;
  const rows: PermissionSelectorRow[] = [
    {
      type: "group",
      id: `group:${group.key}`,
      group,
      depth,
      isExpanded,
      selectedCount: childPermissions.filter((permission) => isPermissionSelected(permission.key, selectedKeys)).length,
      permissionCount: childPermissions.length,
      selectionState: groupSelectionState(group, selectedKeys),
      scopeOptions: groupScopeOptions(group),
      isExiting: isAncestorExiting,
    },
  ];

  if (!isExpanded && !isGroupExiting) {
    return rows;
  }

  rows.push(
    ...(group.permissions ?? []).map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: depth + 1,
      isExiting: isChildExiting,
    })),
    ...childGroups.flatMap((childGroup) => buildGroupRows(childGroup, depth + 1, expandedGroupKeys, exitingGroupKeys, selectedKeys, isChildExiting)),
  );

  return rows;
}

function depthStyle(depth: number): CSSProperties {
  return { "--permission-depth": depth } as CSSProperties;
}

function isPermissionSelected(permissionKey: string, selectedKeys: string[]): boolean {
  return selectedKeys.some((key) => directGrantSelectionPermissionKey(key) === permissionKey);
}

function useExitingGroupKeys(expandedGroupKeys: string[]): string[] {
  const previousExpandedGroupKeys = useRef(expandedGroupKeys);
  const [exitingGroupKeys, setExitingGroupKeys] = useState<string[]>([]);

  useEffect(() => {
    const removedGroupKeys = previousExpandedGroupKeys.current.filter((key) => !expandedGroupKeys.includes(key));
    previousExpandedGroupKeys.current = expandedGroupKeys;
    if (removedGroupKeys.length === 0) {
      setExitingGroupKeys((current) => current.filter((key) => !expandedGroupKeys.includes(key)));
      return;
    }

    setExitingGroupKeys((current) => Array.from(new Set([...current, ...removedGroupKeys])));
    const timeoutId = window.setTimeout(() => {
      setExitingGroupKeys((current) => current.filter((key) => !removedGroupKeys.includes(key)));
    }, EXIT_ANIMATION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [expandedGroupKeys]);

  return exitingGroupKeys.filter((key) => !expandedGroupKeys.includes(key));
}

function groupSelectionState(group: ScopedPermissionGroupItem, selectedKeys: string[]): GroupSelectionState {
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
  if (scopes.length > 1) {
    return scopes.map((scope) => directGrantSelectionKey(permission.key, scope.key));
  }
  return [permission.key];
}

function groupScopeOptions(group: ScopedPermissionGroupItem): string[] {
  return Array.from(
    new Set(
      collectScopedGroupPermissions(group).flatMap((permission) => (permission.scopes ?? []).map((scope) => scope.key)),
    ),
  );
}

function joinClassNames(...classNames: Array<string | false | null | undefined>): string {
  return classNames.filter(Boolean).join(" ");
}

function groupRowClickHandler(
  row: PermissionSelectorRow,
  onToggleGroup: (key: string) => void,
): (() => void) | undefined {
  return row.type === "group" ? () => onToggleGroup(row.group.key) : undefined;
}

function collectScopedGroupPermissions(group: ScopedPermissionGroupItem): ScopedPermissionItem[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  return [...(group.permissions ?? []), ...childGroups.flatMap((childGroup) => collectScopedGroupPermissions(childGroup))];
}
