import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { CSSProperties, MouseEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
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
  onPermissionScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
  onPermissionGroupScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  onSelectPermissionKeys: (selectionKeys: string[]) => void;
  onClearPermissionKeys: (selectionKeys: string[]) => void;
  onExpandGroups: (groupKeys: string[]) => void;
  onCollapseGroups: (groupKeys: string[]) => void;
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

type GroupSelectionState = "checked" | "indeterminate" | "unchecked";
type ScopeOptionView = NonNullable<ScopedPermissionItem["scopes"]>[number];

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
  onPermissionScopeChange,
  onPermissionGroupScopeChange,
  onSelectPermissionKeys,
  onClearPermissionKeys,
  onExpandGroups,
  onCollapseGroups,
  onToggleGroup,
}: PermissionSelectorProps) {
  const exitingGroupKeys = useExitingGroupKeys(expandedGroupKeys);
  const enteringGroupKeys = useEnteringGroupKeys(expandedGroupKeys);
  const rows = useMemo(
    () => buildPermissionRows(groups, ungroupedPermissions, expandedGroupKeys, enteringGroupKeys, exitingGroupKeys, selectedKeys),
    [enteringGroupKeys, expandedGroupKeys, exitingGroupKeys, groups, selectedKeys, ungroupedPermissions],
  );
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const displayRows = useMemo(
    () => (showSelectedOnly ? filterRowsToSelected(rows) : rows),
    [rows, showSelectedOnly],
  );
  const toolbarStats = useMemo(
    () => buildPermissionSelectorToolbarStats(selectedKeys, selectedScopes),
    [selectedKeys, selectedScopes],
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
        header: "权限范围",
        cell: ({ row }) =>
          row.original.type === "group" ? (
            <PermissionGroupScopeCell
              group={row.original.group}
              scopeOptions={row.original.scopeOptions}
              selectedKeys={selectedKeys}
              onScopeChange={onPermissionGroupScopeChange}
            />
          ) : (
            <PermissionScopeCell
              permission={row.original.permission}
              selectedKeys={selectedKeys}
              onScopeChange={onPermissionScopeChange}
            />
          ),
      },
    ],
    [onPermissionGroupScopeChange, onPermissionScopeChange, onToggleGroup, selectedKeys],
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
  const currentPageRows = table.getRowModel().rows;

  return (
    <div className="permission-selector__surface">
      <PermissionSelectorToolbar
        selectedCount={toolbarStats.selectedCount}
        configuredScopeCount={toolbarStats.configuredScopeCount}
        showSelectedOnly={showSelectedOnly}
        onShowSelectedOnlyChange={setShowSelectedOnly}
        onExpandAll={() => onExpandGroups(currentPageGroupKeysFromRows(currentPageRows))}
        onCollapseAll={() => onCollapseGroups(currentPageGroupKeysFromRows(currentPageRows))}
        onSelectAll={() => onSelectPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows))}
        onClear={() => onClearPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows))}
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
                      header.column.id === "permission" && "permission-selector__sticky-column permission-selector__sticky-column--header",
                      header.column.id === "scope" && "permission-selector__scope-cell",
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
                    row.original.isEntering && "permission-selector__row--entering",
                    row.original.isExiting && "permission-selector__row--exiting",
                  )}
                  onClick={groupRowClickHandler(row.original, onToggleGroup)}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className={joinClassNames(
                        "border-b border-ink/8 px-3 py-2.5 align-middle text-[13px] text-ink",
                        cell.column.id === "permission" && "permission-selector__sticky-column",
                        cell.column.id === "scope" && "permission-selector__scope-cell",
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
  showSelectedOnly,
  onShowSelectedOnlyChange,
  onExpandAll,
  onCollapseAll,
  onSelectAll,
  onClear,
}: {
  selectedCount: number;
  configuredScopeCount: number;
  showSelectedOnly: boolean;
  onShowSelectedOnlyChange: (showSelectedOnly: boolean) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  return (
    <div className="permission-selector__toolbar">
      <div className="permission-selector__toolbar-stats" aria-label="权限选择状态">
        <span className="permission-selector__toolbar-stat">已选 {selectedCount} 项</span>
        <span className="permission-selector__toolbar-stat">已设置权限范围 {configuredScopeCount} 项</span>
      </div>
      <div className="permission-selector__toolbar-actions">
        <button type="button" className="permission-selector__toolbar-button" onClick={onExpandAll}>
          展开全部
        </button>
        <button type="button" className="permission-selector__toolbar-button" onClick={onCollapseAll}>
          折叠全部
        </button>
        <button type="button" className="permission-selector__toolbar-button" onClick={onSelectAll}>
          全选
        </button>
        <button type="button" className="permission-selector__toolbar-button" onClick={onClear}>
          清空
        </button>
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
  selectedKeys,
  onScopeChange,
}: {
  group: ScopedPermissionGroupItem;
  scopeOptions: ScopeOptionView[];
  selectedKeys: string[];
  onScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
}) {
  if (scopeOptions.length === 0) {
    return <span aria-label="权限组无权限范围">-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopeOptions.map((scope) => {
        const selectionState = groupScopeSelectionState(group, scope.key, selectedKeys);

        return (
          <ScopeChip
            key={scope.key}
            label={scope.name}
            checked={selectionState === "checked"}
            mixed={selectionState === "indeterminate"}
            ariaLabel={`选择权限组 ${group.key} ${scope.name}`}
            onChange={() => onScopeChange(group, scope.key, selectionState === "unchecked")}
          />
        );
      })}
    </div>
  );
}

function PermissionScopeCell({
  permission,
  selectedKeys,
  onScopeChange,
}: {
  permission: ScopedPermissionItem;
  selectedKeys: string[];
  onScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
}) {
  const scopes = permission.scopes ?? [];
  if (scopes.length === 0) {
    return <span aria-label={`${permission.key} 无权限范围`}>-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopes.map((scope) => (
        <ScopeChip
          key={scope.key}
          label={scope.name}
          checked={selectedKeys.includes(directGrantSelectionKey(permission.key, scope.key))}
          ariaLabel={`选择 ${permission.key} ${scope.name}`}
          onChange={() => onScopeChange(permission, scope.key)}
        />
      ))}
    </div>
  );
}

function ScopeChip({
  label,
  checked,
  mixed = false,
  ariaLabel,
  onChange,
}: {
  label: string;
  checked: boolean;
  mixed?: boolean;
  ariaLabel: string;
  onChange: () => void;
}) {
  const checkboxRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = mixed;
    }
  }, [mixed]);

  return (
    <label
      className={joinClassNames(
        "permission-selector__scope-chip",
        checked && "permission-selector__scope-chip--checked",
        mixed && "permission-selector__scope-chip--mixed",
      )}
    >
      <input
        ref={checkboxRef}
        type="checkbox"
        checked={checked}
        aria-checked={mixed ? "mixed" : checked}
        onChange={onChange}
        aria-label={ariaLabel}
      />
      <span>{label}</span>
    </label>
  );
}

interface PermissionSelectorToolbarStats {
  selectedCount: number;
  configuredScopeCount: number;
}

function buildPermissionSelectorToolbarStats(
  selectedKeys: string[],
  selectedScopes: Record<string, string>,
): PermissionSelectorToolbarStats {
  return {
    selectedCount: selectedKeys.length,
    configuredScopeCount: countConfiguredScopes(selectedScopes),
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
  enteringGroupKeys: string[],
  exitingGroupKeys: string[],
  selectedKeys: string[],
): PermissionSelectorRow[] {
  return [
    ...groups.flatMap((group) => buildGroupRows(group, 0, expandedGroupKeys, enteringGroupKeys, exitingGroupKeys, selectedKeys, false, false)),
    ...ungroupedPermissions.map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: 0,
      isSelected: isPermissionSelected(permission.key, selectedKeys),
      isEntering: false,
      isExiting: false,
    })),
  ];
}

function buildGroupRows(
  group: ScopedPermissionGroupItem,
  depth: number,
  expandedGroupKeys: string[],
  enteringGroupKeys: string[],
  exitingGroupKeys: string[],
  selectedKeys: string[],
  isAncestorEntering: boolean,
  isAncestorExiting: boolean,
): PermissionSelectorRow[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const directChildPermissions = (group.children ?? []).filter((child): child is ScopedPermissionItem => !isPermissionGroupItem(child));
  const descendantPermissions = collectScopedGroupPermissions(group);
  const isExpanded = expandedGroupKeys.includes(group.key);
  const isGroupEntering = enteringGroupKeys.includes(group.key);
  const isGroupExiting = exitingGroupKeys.includes(group.key);
  const isChildEntering = isAncestorEntering || isGroupEntering;
  const isChildExiting = isAncestorExiting || isGroupExiting;
  const rows: PermissionSelectorRow[] = [
    {
      type: "group",
      id: `group:${group.key}`,
      group,
      depth,
      isExpanded,
      selectedCount: descendantPermissions.filter((permission) => isPermissionSelected(permission.key, selectedKeys)).length,
      permissionCount: descendantPermissions.length,
      selectionState: groupSelectionState(group, selectedKeys),
      scopeOptions: groupScopeOptions(group),
      isEntering: isAncestorEntering,
      isExiting: isAncestorExiting,
    },
  ];

  const shouldRenderChildren = isExpanded || (isGroupExiting && !isAncestorEntering);

  if (!shouldRenderChildren) {
    return rows;
  }

  rows.push(
    ...(group.permissions ?? []).map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: depth + 1,
      isSelected: isPermissionSelected(permission.key, selectedKeys),
      isEntering: isChildEntering,
      isExiting: isChildExiting,
    })),
    ...directChildPermissions.map((permission) => ({
      type: "permission" as const,
      id: `permission:${permission.key}`,
      permission,
      depth: depth + 1,
      isSelected: isPermissionSelected(permission.key, selectedKeys),
      isEntering: isChildEntering,
      isExiting: isChildExiting,
    })),
    ...childGroups.flatMap((childGroup) =>
      buildGroupRows(
        childGroup,
        depth + 1,
        expandedGroupKeys,
        enteringGroupKeys,
        exitingGroupKeys,
        selectedKeys,
        isChildEntering,
        isChildExiting,
      ),
    ),
  );

  return rows;
}

function depthStyle(depth: number): CSSProperties {
  return { "--permission-depth": depth } as CSSProperties;
}

function isPermissionSelected(permissionKey: string, selectedKeys: string[]): boolean {
  return selectedKeys.some((key) => directGrantSelectionPermissionKey(key) === permissionKey);
}

function useEnteringGroupKeys(expandedGroupKeys: string[]): string[] {
  const previousExpandedGroupKeys = useRef(expandedGroupKeys);
  const [enteringGroupKeys, setEnteringGroupKeys] = useState<string[]>([]);

  useEffect(() => {
    const addedGroupKeys = expandedGroupKeys.filter((key) => !previousExpandedGroupKeys.current.includes(key));
    previousExpandedGroupKeys.current = expandedGroupKeys;
    if (addedGroupKeys.length === 0) {
      setEnteringGroupKeys((current) => {
        const next = current.filter((key) => expandedGroupKeys.includes(key));
        return stringListsAreEqual(current, next) ? current : next;
      });
      return;
    }

    setEnteringGroupKeys((current) => {
      const next = Array.from(new Set([...current, ...addedGroupKeys]));
      return stringListsAreEqual(current, next) ? current : next;
    });
    const timeoutId = window.setTimeout(() => {
      setEnteringGroupKeys((current) => {
        const next = current.filter((key) => !addedGroupKeys.includes(key));
        return stringListsAreEqual(current, next) ? current : next;
      });
    }, EXIT_ANIMATION_MS);
    return () => window.clearTimeout(timeoutId);
  }, [expandedGroupKeys]);

  return useMemo(
    () => enteringGroupKeys.filter((key) => expandedGroupKeys.includes(key)),
    [enteringGroupKeys, expandedGroupKeys],
  );
}

function useExitingGroupKeys(expandedGroupKeys: string[]): string[] {
  const previousExpandedGroupKeys = useRef(expandedGroupKeys);
  const timeoutIdsByKey = useRef(new Map<string, number>());
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
    for (const removedGroupKey of removedGroupKeys) {
      if (timeoutIdsByKey.current.has(removedGroupKey)) {
        continue;
      }
      const timeoutId = window.setTimeout(() => {
        timeoutIdsByKey.current.delete(removedGroupKey);
        setExitingGroupKeys((current) => {
          const next = current.filter((key) => key !== removedGroupKey);
          return stringListsAreEqual(current, next) ? current : next;
        });
      }, EXIT_ANIMATION_MS);
      timeoutIdsByKey.current.set(removedGroupKey, timeoutId);
    }
  }, [expandedGroupKeys]);

  useEffect(() => {
    const timeoutIds = timeoutIdsByKey.current;
    return () => {
      for (const timeoutId of timeoutIds.values()) {
        window.clearTimeout(timeoutId);
      }
      timeoutIds.clear();
    };
  }, []);

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
  return scopes.map((scope) => directGrantSelectionKey(permission.key, scope.key));
}

function groupScopeSelectionState(group: ScopedPermissionGroupItem, scopeKey: string, selectedKeys: string[]): GroupSelectionState {
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

function currentPageSelectionKeysFromRows(rows: Array<{ original: PermissionSelectorRow }>): string[] {
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
  return Array.from(permissionsByKey.values()).flatMap((permission) => permissionSelectionKeys(permission));
}

function currentPageGroupKeysFromRows(rows: Array<{ original: PermissionSelectorRow }>): string[] {
  return rows.map((row) => row.original).filter((row) => row.type === "group").map((row) => row.group.key);
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
): ((event: MouseEvent<HTMLTableRowElement>) => void) | undefined {
  return row.type === "group"
    ? (event) => {
        if (eventTargetIsInteractive(event.target)) {
          return;
        }
        onToggleGroup(row.group.key);
      }
    : undefined;
}

function eventTargetIsInteractive(target: EventTarget): boolean {
  return target instanceof Element && Boolean(target.closest("a,button,input,label,select,textarea"));
}

function collectScopedGroupPermissions(group: ScopedPermissionGroupItem): ScopedPermissionItem[] {
  const childGroups = (group.children ?? []).filter(isPermissionGroupItem);
  const childPermissions = (group.children ?? []).filter((child): child is ScopedPermissionItem => !isPermissionGroupItem(child));
  return [
    ...(group.permissions ?? []),
    ...childPermissions,
    ...childGroups.flatMap((childGroup) => collectScopedGroupPermissions(childGroup)),
  ];
}
