import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";
import { useEffect, useMemo, useRef, useState } from "react";
import { EmptyState } from "../../../components/ui/EmptyState";
import { PaginationBar } from "../../../components/ui/PaginationBar";
import {
  TABLE_HEAD_CLASS,
  TABLE_HEADER_CELL_CLASS,
  TABLE_ROOT_CLASS,
  TABLE_ROW_CLASS,
} from "../../../components/ui/tableStyles";
import { cn } from "../../../lib/cn";
import { useI18n } from "../../../i18n/I18nProvider";
import type { Translator } from "../../../lib/status";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { PermissionSelectorBody } from "./PermissionSelectorBody";
import { PermissionSelectorScopeMenu } from "./PermissionSelectorScopeMenu";
import { permissionSelectorColumns } from "./permissionSelectorColumns";
import {
  buildPermissionRows,
  currentPageGroupKeysFromRows,
  currentPageSelectionKeysFromRows,
  filterRowsToSelected,
  type PermissionSelectorRow,
} from "./permissionSelectorRows";

interface PermissionSelectorProps {
  appKey: string;
  groups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  selectedKeys: string[];
  /** 所选权限组已覆盖的权限范围: 展示为勾选且禁用, 不参与直接权限提交。 */
  coveredKeys?: string[];
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
  disabled?: boolean;
}

const EXIT_ANIMATION_MS = 160;

function motionDurationMs(fullMs: number): number {
  if (typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    return 0;
  }
  return fullMs;
}

export function PermissionSelector({
  appKey,
  groups,
  ungroupedPermissions,
  selectedKeys,
  coveredKeys = [],
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
  disabled = false,
}: PermissionSelectorProps) {
  const { locale, t } = useI18n();
  const exitingGroupKeys = useExitingGroupKeys(expandedGroupKeys);
  const enteringGroupKeys = useEnteringGroupKeys(expandedGroupKeys);
  const coveredKeySet = useMemo(() => new Set(coveredKeys), [coveredKeys]);
  // 展示态 = 直接勾选 ∪ 权限组覆盖; 提交载荷仍只用直接勾选(selectedKeys)。
  const displaySelectedKeys = useMemo(
    () => Array.from(new Set([...selectedKeys, ...coveredKeys])),
    [coveredKeys, selectedKeys],
  );
  const rows = useMemo(
    () =>
      buildPermissionRows(groups, ungroupedPermissions, {
        expandedGroupKeys,
        enteringGroupKeys,
        exitingGroupKeys,
        selectedKeys: displaySelectedKeys,
      }),
    [enteringGroupKeys, expandedGroupKeys, exitingGroupKeys, groups, displaySelectedKeys, ungroupedPermissions],
  );
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const displayRows = useMemo(
    () => (showSelectedOnly ? filterRowsToSelected(rows) : rows),
    [rows, showSelectedOnly],
  );
  const columns = useMemo<ColumnDef<PermissionSelectorRow>[]>(
    () =>
      permissionSelectorColumns({
        t,
        locale,
        displaySelectedKeys,
        coveredKeySet,
        onPermissionScopeChange,
        onPermissionGroupScopeChange,
        onToggleGroup,
      }),
    [coveredKeySet, displaySelectedKeys, locale, onPermissionGroupScopeChange, onPermissionScopeChange, onToggleGroup, t],
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

  const placeholder = selectorPlaceholder({ appKey, loading, errorMessage, isEmpty: rows.length === 0 }, t);
  if (placeholder) {
    return (
      <div className="permission-selector__surface">
        <EmptyState title={placeholder.title} description={placeholder.description} />
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
        onSelectAll={() => onSelectPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows).filter((key) => !coveredKeySet.has(key)))}
        onSelectScope={(scopeKey) => onSelectPermissionKeys(currentPageSelectionKeysFromRows(currentPageRows, scopeKey).filter((key) => !coveredKeySet.has(key)))}
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
          <PermissionSelectorBody
            rows={visibleRows}
            columnCount={table.getAllLeafColumns().length}
            disabled={disabled}
            showSelectedOnly={showSelectedOnly}
            onToggleGroup={onToggleGroup}
          />
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

/** 无应用/加载中/加载失败/无数据四种占位态: 命中任一即整表让位给占位文案。 */
function selectorPlaceholder(
  state: { appKey: string; loading: boolean; errorMessage: string; isEmpty: boolean },
  t: Translator,
): { title: string; description: string } | null {
  if (!state.appKey) {
    return { title: t("selector.selectAppFirst.title"), description: t("selector.selectAppFirst.description") };
  }
  if (state.loading) {
    return { title: t("selector.loading.title"), description: t("selector.loading.description") };
  }
  if (state.errorMessage) {
    return { title: t("selector.loadFailed.title"), description: state.errorMessage };
  }
  if (state.isEmpty) {
    return { title: t("selector.empty.title"), description: t("selector.empty.description") };
  }
  return null;
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
        <PermissionSelectorScopeMenu onSelectAll={onSelectAll} onSelectScope={onSelectScope} />
        <button type="button" className="permission-selector__toolbar-button" onClick={onClear}>
          {t("selector.toolbar.clear")}
        </button>
      </div>
    </div>
  );
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
    }, motionDurationMs(EXIT_ANIMATION_MS));
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
  const generationByKey = useRef(new Map<string, number>());
  const [exitingGroupKeys, setExitingGroupKeys] = useState<string[]>([]);

  useEffect(() => {
    const removedGroupKeys = previousExpandedGroupKeys.current.filter((key) => !expandedGroupKeys.includes(key));
    previousExpandedGroupKeys.current = expandedGroupKeys;
    // 重新展开时取消对应退出 generation/timer, 避免旧 timer 提前结束新动画。
    for (const key of expandedGroupKeys) {
      const existingTimer = timeoutIdsByKey.current.get(key);
      if (existingTimer !== undefined) {
        window.clearTimeout(existingTimer);
        timeoutIdsByKey.current.delete(key);
      }
      generationByKey.current.set(key, (generationByKey.current.get(key) ?? 0) + 1);
    }
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
      const generation = (generationByKey.current.get(removedGroupKey) ?? 0) + 1;
      generationByKey.current.set(removedGroupKey, generation);
      const existingTimer = timeoutIdsByKey.current.get(removedGroupKey);
      if (existingTimer !== undefined) {
        window.clearTimeout(existingTimer);
      }
      const timeoutId = window.setTimeout(() => {
        timeoutIdsByKey.current.delete(removedGroupKey);
        if (generationByKey.current.get(removedGroupKey) !== generation) {
          return;
        }
        setExitingGroupKeys((current) => {
          const next = current.filter((key) => key !== removedGroupKey);
          return stringListsAreEqual(current, next) ? current : next;
        });
      }, motionDurationMs(EXIT_ANIMATION_MS));
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

function stringListsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}
