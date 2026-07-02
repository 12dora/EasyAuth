import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { SelectInput } from "../../../components/Field";
import { EmptyState } from "../../../components/ui/EmptyState";

import { isPermissionGroupItem } from "../permissionTree";
import {
  directGrantSelectionKey,
  directGrantSelectionPermissionKey,
} from "../hooks/useAccessRequestForm";
import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/useAccessRequestForm";

const MONO_TEXT_CLASS = "font-mono text-[13px] leading-5 text-ink-soft";
const PERMISSION_TABLE_PAGE_SIZE_OPTIONS = [5, 10, 20, 50] as const;

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
      isSelected: boolean;
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
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const displayRows = useMemo(
    () => (showSelectedOnly ? filterRowsToSelected(rows) : rows),
    [rows, showSelectedOnly],
  );
  const toolbarStats = useMemo(
    () => buildPermissionSelectorToolbarStats(rows, displayRows, selectedKeys, selectedScopes),
    [displayRows, rows, selectedKeys, selectedScopes],
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
            <span className="permission-selector__permission-name" style={depthStyle(row.original.depth)}>
              <span className="permission-selector__leaf-marker" aria-hidden="true" />
              <span className="permission-selector__permission-label">{row.original.permission.name}</span>
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
    data: displayRows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (row) => row.id,
  });
  const previousShowSelectedOnly = useRef(showSelectedOnly);

  useEffect(() => {
    if (previousShowSelectedOnly.current !== showSelectedOnly) {
      previousShowSelectedOnly.current = showSelectedOnly;
      table.setPageIndex(0);
    }
  }, [showSelectedOnly, table]);

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
    return (
      <div className="permission-selector__surface">
        <EmptyState title="暂无可选直接权限" description="当前应用未返回可直接申请的权限，可仅选择权限组发起申请。" />
      </div>
    );
  }

  const pagination = table.getState().pagination;
  const totalRows = table.getPrePaginationRowModel().rows.length;
  const visibleRows = table.getRowModel().rows;
  const pageStart = totalRows === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1;
  const pageEnd = totalRows === 0 ? 0 : pageStart + visibleRows.length - 1;

  return (
    <div className="permission-selector__surface">
      <PermissionSelectorToolbar
        selectedCount={toolbarStats.selectedCount}
        configuredScopeCount={toolbarStats.configuredScopeCount}
        visibleCount={toolbarStats.visibleCount}
        totalCount={toolbarStats.totalCount}
        showSelectedOnly={showSelectedOnly}
        onShowSelectedOnlyChange={setShowSelectedOnly}
      />
      <div className="overflow-x-auto">
        <table aria-label="权限选择" className="min-w-full border-separate border-spacing-0 text-[13px]">
          <thead className="bg-paper-deep/60">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className="group transition-colors hover:bg-[rgb(var(--amber))]/[0.05]">
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    colSpan={header.colSpan}
                    className={joinClassNames(
                      "border-b border-ink/15 px-3 py-2.5 text-left align-bottom font-mono text-[10.5px] font-medium uppercase tracking-[0.14em] text-ink-soft",
                      header.column.id === "permission" && "sticky left-0 z-20 bg-paper-deep/95",
                    )}
                  >
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {visibleRows.length > 0 ? (
              visibleRows.map((row) => (
                <tr
                  key={row.id}
                  className={joinClassNames(
                    "group transition-colors hover:bg-[rgb(var(--amber))]/[0.05]",
                    "permission-selector__row",
                    row.original.type === "group" && "permission-selector__row--group bg-paper-deep/60 hover:bg-paper-deep",
                    row.original.type === "group" && row.original.selectionState !== "unchecked" && "permission-selector__row--group-selected",
                    row.original.type === "permission" && row.original.isSelected && "permission-selector__row--selected",
                    row.original.isExiting && "permission-selector__row--exiting",
                  )}
                  onClick={groupRowClickHandler(row.original, onToggleGroup)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={joinClassNames(
                        "border-b border-ink/8 px-3 py-2.5 align-middle text-[13px] text-ink",
                        cell.column.id === "permission" && "sticky left-0 z-10 bg-inherit",
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr className="group transition-colors hover:bg-transparent">
                <td colSpan={table.getAllLeafColumns().length} className="border-b border-ink/8 px-3 py-10 text-center text-[13px] text-ink-soft">
                  <EmptyState
                    title={showSelectedOnly ? "当前没有已选直接权限" : "暂无可选直接权限"}
                    description={
                      showSelectedOnly
                        ? "关闭仅看已选后可继续浏览并选择权限。"
                        : "当前应用未返回可直接申请的权限，可仅选择权限组发起申请。"
                    }
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-ink/10 bg-paper-deep/30 px-3 py-2.5">
        <span className="text-[12px] font-medium text-ink-soft">
          第 {pageStart}-{pageEnd} 条 / 共 {totalRows} 条
        </span>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-[12px] font-medium text-ink-soft">
            每页
            <select
              aria-label="每页条目数"
              className="h-8 w-20 rounded-[3px] border border-[rgb(var(--hairline-strong))] bg-paper px-2 text-[13px] text-ink outline-none transition-colors focus:border-[rgb(var(--amber))] focus:ring-2 focus:ring-[rgb(var(--amber)_/_0.18)]"
              value={String(pagination.pageSize)}
              onChange={(event) => {
                table.setPageIndex(0);
                table.setPageSize(Number(event.currentTarget.value));
              }}
            >
              {PERMISSION_TABLE_PAGE_SIZE_OPTIONS.map((pageSize) => (
                <option key={pageSize} value={pageSize}>
                  {pageSize}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="上一页"
              className="inline-flex h-8 w-8 items-center justify-center rounded-[3px] border border-[rgb(var(--hairline-strong))] bg-paper text-ink transition-colors hover:border-[rgb(var(--amber))] hover:bg-[rgb(var(--amber))]/[0.08] disabled:cursor-not-allowed disabled:opacity-45"
              disabled={!table.getCanPreviousPage()}
              onClick={() => table.previousPage()}
            >
              <ChevronLeft size={15} aria-hidden="true" />
            </button>
            <span className="min-w-16 text-center font-mono text-[12px] text-ink-soft">
              {table.getPageCount() === 0 ? 0 : pagination.pageIndex + 1} / {table.getPageCount()}
            </span>
            <button
              type="button"
              aria-label="下一页"
              className="inline-flex h-8 w-8 items-center justify-center rounded-[3px] border border-[rgb(var(--hairline-strong))] bg-paper text-ink transition-colors hover:border-[rgb(var(--amber))] hover:bg-[rgb(var(--amber))]/[0.08] disabled:cursor-not-allowed disabled:opacity-45"
              disabled={!table.getCanNextPage()}
              onClick={() => table.nextPage()}
            >
              <ChevronRight size={15} aria-hidden="true" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PermissionSelectorToolbar({
  selectedCount,
  configuredScopeCount,
  visibleCount,
  totalCount,
  showSelectedOnly,
  onShowSelectedOnlyChange,
}: {
  selectedCount: number;
  configuredScopeCount: number;
  visibleCount: number;
  totalCount: number;
  showSelectedOnly: boolean;
  onShowSelectedOnlyChange: (showSelectedOnly: boolean) => void;
}) {
  return (
    <div className="permission-selector__toolbar">
      <div className="permission-selector__toolbar-stats" aria-label="权限选择状态">
        <span className="permission-selector__toolbar-stat">已选 {selectedCount} 项</span>
        <span className="permission-selector__toolbar-stat">scope 已设置 {configuredScopeCount} 项</span>
        <span className="permission-selector__toolbar-stat">当前显示 {visibleCount}/{totalCount}</span>
      </div>
      <label className="permission-selector__toolbar-toggle">
        <input
          type="checkbox"
          role="switch"
          aria-label="仅看已选"
          checked={showSelectedOnly}
          onChange={(event) => onShowSelectedOnlyChange(event.currentTarget.checked)}
        />
        <span aria-hidden="true" className="permission-selector__toolbar-toggle-track">
          <span className="permission-selector__toolbar-toggle-thumb" />
        </span>
        <span>仅看已选</span>
      </label>
    </div>
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
      className="permission-selector__group-button"
      onClick={(event) => {
        event.stopPropagation();
        onToggleGroup(group.key);
      }}
      aria-expanded={isExpanded}
      aria-label={`${isExpanded ? "收起" : "展开"} ${group.name}`}
      style={depthStyle(depth)}
    >
      <span className="permission-selector__tree-rail" aria-hidden="true" />
      <ChevronRight size={16} className={isExpanded ? "permission-selector__chevron permission-selector__chevron--expanded" : "permission-selector__chevron"} />
      <span className="permission-selector__group-name">{group.name}</span>
      <span className={selectedCount > 0 ? "permission-selector__group-count permission-selector__group-count--active" : "permission-selector__group-count"}>
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
      className="permission-selector__scope-bulk-select"
      value=""
      onClick={(event) => event.stopPropagation()}
      onChange={(event) => onScopeChange(group, event.currentTarget.value)}
      aria-label={`${group.key} 权限组 scope`}
    >
      <option value="">批量应用 scope</option>
      {scopeOptions.map((scopeKey) => (
        <option key={scopeKey} value={scopeKey}>
          应用 {scopeKey}
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
        <div className="permission-selector__scope-chip-list">
          {scopes.map((scope) => {
            const selectionKey = directGrantSelectionKey(permission.key, scope.key);

            return (
              <label
                key={scope.key}
                className={joinClassNames(
                  "permission-selector__scope-chip",
                  selectedKeys.includes(selectionKey) && "permission-selector__scope-chip--checked",
                )}
              >
                <input
                  type="checkbox"
                  checked={selectedKeys.includes(selectionKey)}
                  onClick={(event) => event.stopPropagation()}
                  onChange={() => onToggle(selectionKey)}
                  aria-label={`选择 ${permission.key} ${scope.key}`}
                />
                <span>
                  {scope.name} ({scope.key})
                </span>
              </label>
            );
          })}
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
        <span className="permission-selector__selection-hint" aria-label={`${permission.key} 多 scope 选择`}>
          按 scope 选择
        </span>
      )}
    </>
  );
}

interface PermissionSelectorToolbarStats {
  selectedCount: number;
  configuredScopeCount: number;
  visibleCount: number;
  totalCount: number;
}

function buildPermissionSelectorToolbarStats(
  rows: PermissionSelectorRow[],
  displayRows: PermissionSelectorRow[],
  selectedKeys: string[],
  selectedScopes: Record<string, string>,
): PermissionSelectorToolbarStats {
  return {
    selectedCount: selectedKeys.length,
    configuredScopeCount: countConfiguredScopes(selectedScopes),
    visibleCount: displayRows.length,
    totalCount: rows.length,
  };
}

function countConfiguredScopes(selectedScopes: Record<string, string>): number {
  return Object.values(selectedScopes).filter(Boolean).length;
}

function filterRowsToSelected(rows: PermissionSelectorRow[]): PermissionSelectorRow[] {
  return rows.filter((row) => rowMatchesSelected(row));
}

function rowMatchesSelected(row: PermissionSelectorRow): boolean {
  if (row.type === "group") {
    return row.selectionState !== "unchecked";
  }
  return row.isSelected;
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
      isSelected: isPermissionSelected(permission.key, selectedKeys),
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
      isSelected: isPermissionSelected(permission.key, selectedKeys),
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
      setExitingGroupKeys((current) => {
        const next = current.filter((key) => !expandedGroupKeys.includes(key));
        return stringListsAreEqual(current, next) ? current : next;
      });
      return;
    }

    setExitingGroupKeys((current) => {
      const next = Array.from(new Set([...current, ...removedGroupKeys]));
      return stringListsAreEqual(current, next) ? current : next;
    });
    const timeoutId = window.setTimeout(() => {
      setExitingGroupKeys((current) => {
        const next = current.filter((key) => !removedGroupKeys.includes(key));
        return stringListsAreEqual(current, next) ? current : next;
      });
    }, EXIT_ANIMATION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [expandedGroupKeys]);

  return useMemo(
    () => exitingGroupKeys.filter((key) => !expandedGroupKeys.includes(key)),
    [expandedGroupKeys, exitingGroupKeys],
  );
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

function stringListsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
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
