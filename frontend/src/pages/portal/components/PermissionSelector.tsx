import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { CSSProperties, MouseEvent } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PaginationBar } from "../../../components/ui/PaginationBar";
import {
  MONO_TEXT_CLASS,
  TABLE_CELL_CLASS,
  TABLE_HEAD_CLASS,
  TABLE_HEADER_CELL_CLASS,
  TABLE_ROOT_CLASS,
  TABLE_ROW_CLASS,
} from "../../../components/ui/tableStyles";
import { cn } from "../../../lib/cn";
import { localizedName, useI18n } from "../../../i18n/I18nProvider";
import type { Locale, MessageKey } from "../../../i18n/messages";

import { isPermissionGroupItem } from "../permissionTree";
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
  const { locale, t } = useI18n();
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
  const columns = useMemo<ColumnDef<PermissionSelectorRow>[]>(
    () => [
      {
        id: "permission",
        header: t("selector.column.permission"),
        cell: ({ row }) =>
          row.original.type === "group" ? (
            <PermissionGroupNameCell
              group={row.original.group}
              depth={row.original.depth}
              isExpanded={row.original.isExpanded}
              selectedCount={row.original.selectedCount}
              permissionCount={row.original.permissionCount}
              onToggleGroup={onToggleGroup}
              locale={locale}
            />
          ) : (
            <span className="permission-selector__permission-name" style={depthStyle(row.original.depth)}>
              <span className="permission-selector__leaf-marker" aria-hidden="true" />
              <span className="permission-selector__permission-label">{localizedName(locale, row.original.permission)}</span>
            </span>
          ),
      },
      {
        id: "key",
        header: t("selector.column.key"),
        cell: ({ row }) => (
          <code className={MONO_TEXT_CLASS}>
            {row.original.type === "group" ? row.original.group.key : row.original.permission.key}
          </code>
        ),
      },
      {
        id: "scope",
        header: t("selector.column.scope"),
        cell: ({ row }) =>
          row.original.type === "group" ? (
            <PermissionGroupScopeCell
              group={row.original.group}
              scopeOptions={row.original.scopeOptions}
              selectedKeys={selectedKeys}
              onScopeChange={onPermissionGroupScopeChange}
              locale={locale}
            />
          ) : (
            <PermissionScopeCell
              permission={row.original.permission}
              selectedKeys={selectedKeys}
              onScopeChange={onPermissionScopeChange}
              locale={locale}
            />
          ),
      },
    ],
    [locale, onPermissionGroupScopeChange, onPermissionScopeChange, onToggleGroup, selectedKeys, t],
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
    return (
      <div className="permission-selector__surface">
        <EmptyState title={t("selector.selectAppFirst.title")} description={t("selector.selectAppFirst.description")} />
      </div>
    );
  }
  if (loading) {
    return (
      <div className="permission-selector__surface">
        <EmptyState title={t("selector.loading.title")} description={t("selector.loading.description")} />
      </div>
    );
  }
  if (errorMessage) {
    return (
      <div className="permission-selector__surface">
        <EmptyState title={t("selector.loadFailed.title")} description={errorMessage} />
      </div>
    );
  }
  if (rows.length === 0) {
    return (
      <div className="permission-selector__surface">
        <EmptyState title={t("selector.empty.title")} description={t("selector.empty.description")} />
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
        selectedCount={selectedKeys.length}
        showSelectedOnly={showSelectedOnly}
        onShowSelectedOnlyChange={setShowSelectedOnly}
        onExpandAll={() => onExpandGroups(currentPageGroupKeysFromRows(currentPageRows))}
        onCollapseAll={() => onCollapseGroups(currentPageGroupKeysFromRows(currentPageRows))}
        onSelectAll={() => onSelectPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows))}
        onSelectScope={(scopeKey) => onSelectPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows, scopeKey))}
        onClear={() => onClearPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows))}
      />
      <div className="overflow-x-auto">
        <table aria-label={t("selector.ariaLabel")} className={TABLE_ROOT_CLASS}>
          <thead className={TABLE_HEAD_CLASS}>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id} className={TABLE_ROW_CLASS}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    colSpan={header.colSpan}
                    className={cn(
                      TABLE_HEADER_CELL_CLASS,
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
                  className={cn(
                    TABLE_ROW_CLASS,
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
                      className={cn(
                        TABLE_CELL_CLASS,
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
                <td colSpan={table.getAllLeafColumns().length} className={cn(TABLE_CELL_CLASS, "py-10 text-center text-ink-soft")}>
                  <EmptyState
                    title={showSelectedOnly ? t("selector.emptySelected.title") : t("selector.empty.title")}
                    description={showSelectedOnly ? t("selector.emptySelected.description") : t("selector.empty.description")}
                  />
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <PaginationBar
        pageStart={pageStart}
        pageEnd={pageEnd}
        totalRows={totalRows}
        pageSize={pagination.pageSize}
        pageIndex={pagination.pageIndex}
        pageCount={table.getPageCount()}
        canPreviousPage={table.getCanPreviousPage()}
        canNextPage={table.getCanNextPage()}
        onPageSizeChange={(pageSize) => {
          table.setPageIndex(0);
          table.setPageSize(pageSize);
        }}
        onPreviousPage={() => table.previousPage()}
        onNextPage={() => table.nextPage()}
      />
    </div>
  );
}

function PermissionSelectorToolbar({
  selectedCount,
  showSelectedOnly,
  onShowSelectedOnlyChange,
  onExpandAll,
  onCollapseAll,
  onSelectAll,
  onSelectScope,
  onClear,
}: {
  selectedCount: number;
  showSelectedOnly: boolean;
  onShowSelectedOnlyChange: (showSelectedOnly: boolean) => void;
  onExpandAll: () => void;
  onCollapseAll: () => void;
  onSelectAll: () => void;
  onSelectScope: (scopeKey: string) => void;
  onClear: () => void;
}) {
  const { t } = useI18n();
  const [selectScopeMenuIsOpen, setSelectScopeMenuIsOpen] = useState(false);
  const selectScopeMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selectScopeMenuIsOpen) {
      return;
    }

    function closeOnOutsidePointerDown(event: PointerEvent) {
      if (!selectScopeMenuRef.current?.contains(event.target as Node)) {
        setSelectScopeMenuIsOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setSelectScopeMenuIsOpen(false);
      }
    }

    document.addEventListener("pointerdown", closeOnOutsidePointerDown);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsidePointerDown);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [selectScopeMenuIsOpen]);

  function selectScope(scopeKey: string) {
    onSelectScope(scopeKey);
    setSelectScopeMenuIsOpen(false);
  }

  const scopeShortcuts: Array<{ scopeKey: string; labelKey: MessageKey }> = [
    { scopeKey: "SELF", labelKey: "selector.scope.self" },
    { scopeKey: "MANAGED_USERS", labelKey: "selector.scope.managedUsers" },
    { scopeKey: "ALL", labelKey: "selector.scope.all" },
  ];

  return (
    <div className="permission-selector__toolbar">
      <div className="permission-selector__toolbar-stats" aria-label={t("selector.toolbar.status")}>
        <span className="permission-selector__toolbar-stat">{t("selector.toolbar.selectedCount", { count: selectedCount })}</span>
        <label className="permission-selector__toolbar-toggle">
          <input
            type="checkbox"
            role="switch"
            aria-label={t("selector.toolbar.showSelectedOnly")}
            checked={showSelectedOnly}
            onChange={(event) => onShowSelectedOnlyChange(event.currentTarget.checked)}
          />
          <span aria-hidden="true" className="permission-selector__toolbar-toggle-track">
            <span className="permission-selector__toolbar-toggle-thumb" />
          </span>
          <span>{t("selector.toolbar.showSelectedOnly")}</span>
        </label>
      </div>
      <div className="permission-selector__toolbar-actions">
        <button type="button" className="permission-selector__toolbar-button" onClick={onExpandAll}>
          {t("selector.toolbar.expandAll")}
        </button>
        <button type="button" className="permission-selector__toolbar-button" onClick={onCollapseAll}>
          {t("selector.toolbar.collapseAll")}
        </button>
        <div ref={selectScopeMenuRef} className="permission-selector__toolbar-split-button">
          <button type="button" className="permission-selector__toolbar-button" onClick={onSelectAll}>
            {t("selector.toolbar.selectAll")}
          </button>
          <button
            type="button"
            className="permission-selector__toolbar-button"
            aria-label={t("selector.toolbar.selectScopeMenu")}
            aria-haspopup="menu"
            aria-expanded={selectScopeMenuIsOpen}
            onClick={() => setSelectScopeMenuIsOpen((isOpen) => !isOpen)}
          >
            <ChevronDown size={15} aria-hidden="true" />
          </button>
          {selectScopeMenuIsOpen ? (
            <div role="menu" className="permission-selector__toolbar-menu">
              {scopeShortcuts.map((shortcut) => (
                <button
                  key={shortcut.scopeKey}
                  type="button"
                  role="menuitem"
                  className="permission-selector__toolbar-menu-item"
                  onClick={() => selectScope(shortcut.scopeKey)}
                >
                  {t(shortcut.labelKey)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <button type="button" className="permission-selector__toolbar-button" onClick={onClear}>
          {t("selector.toolbar.clear")}
        </button>
      </div>
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
  locale,
}: {
  group: ScopedPermissionGroupItem;
  depth: number;
  isExpanded: boolean;
  selectedCount: number;
  permissionCount: number;
  onToggleGroup: (key: string) => void;
  locale: Locale;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      className="permission-selector__group-button"
      onClick={(event) => {
        event.stopPropagation();
        onToggleGroup(group.key);
      }}
      aria-expanded={isExpanded}
      aria-label={`${isExpanded ? t("selector.group.collapse") : t("selector.group.expand")} ${localizedName(locale, group)}`}
      style={depthStyle(depth)}
    >
      <span className="permission-selector__tree-rail" aria-hidden="true" />
      <ChevronRight size={16} className={isExpanded ? "permission-selector__chevron permission-selector__chevron--expanded" : "permission-selector__chevron"} />
      <span className="permission-selector__group-name">{localizedName(locale, group)}</span>
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
  locale,
}: {
  group: ScopedPermissionGroupItem;
  scopeOptions: ScopeOptionView[];
  selectedKeys: string[];
  onScopeChange: (group: ScopedPermissionGroupItem, scopeKey: string, shouldSelect: boolean) => void;
  locale: Locale;
}) {
  const { t } = useI18n();
  if (scopeOptions.length === 0) {
    return <span aria-label={t("selector.group.noScope")}>-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopeOptions.map((scope) => {
        const selectionState = groupScopeSelectionState(group, scope.key, selectedKeys);

        return (
          <ScopeChip
            key={scope.key}
            label={localizedName(locale, scope)}
            checked={selectionState === "checked"}
            mixed={selectionState === "indeterminate"}
            ariaLabel={t("selector.selectGroupScope", { groupKey: group.key, scopeName: localizedName(locale, scope) })}
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
  locale,
}: {
  permission: ScopedPermissionItem;
  selectedKeys: string[];
  onScopeChange: (permission: ScopedPermissionItem, scopeKey: string) => void;
  locale: Locale;
}) {
  const { t } = useI18n();
  const scopes = permission.scopes ?? [];
  if (scopes.length === 0) {
    return <span aria-label={t("selector.permission.noScope", { permissionKey: permission.key })}>-</span>;
  }

  return (
    <div className="permission-selector__scope-chip-list permission-selector__scope-chip-list--single-line">
      {scopes.map((scope) => (
        <ScopeChip
          key={scope.key}
          label={localizedName(locale, scope)}
          checked={selectedKeys.includes(directGrantSelectionKey(permission.key, scope.key))}
          ariaLabel={t("selector.selectPermissionScope", { permissionKey: permission.key, scopeName: localizedName(locale, scope) })}
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
      className={cn(
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
  const childGroups = childGroupsForGroup(group);
  const directPermissions = directPermissionsForGroup(group);
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
    ...directPermissions.map((permission) => ({
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

function currentPageSelectionKeysFromRows(rows: Array<{ original: PermissionSelectorRow }>, scopeKey?: string): string[] {
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

function currentPageGroupKeysFromRows(rows: Array<{ original: PermissionSelectorRow }>): string[] {
  return rows.map((row) => row.original).filter((row) => row.type === "group").map((row) => row.group.key);
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
  const permissionsByKey = new Map<string, ScopedPermissionItem>();
  for (const permission of directPermissionsForGroup(group)) {
    permissionsByKey.set(permission.key, permission);
  }
  for (const childGroup of childGroupsForGroup(group)) {
    for (const permission of collectScopedGroupPermissions(childGroup)) {
      permissionsByKey.set(permission.key, permission);
    }
  }
  return Array.from(permissionsByKey.values());
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
