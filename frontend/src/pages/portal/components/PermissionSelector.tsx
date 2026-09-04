import { getCoreRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EmptyState } from "../../../components/ui/EmptyState";
import { useI18n } from "../../../i18n/I18nProvider";
import type { Translator } from "../../../lib/status";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { PermissionSelectorTable } from "./PermissionSelectorTable";
import { PermissionSelectorToolbar } from "./PermissionSelectorToolbar";
import { permissionSelectorColumns } from "./permissionSelectorColumns";
import {
  buildPermissionRows,
  currentPageGroupKeysFromRows,
  currentPageSelectionKeysFromRows,
  filterRowsToSelected,
  type PermissionSelectorRow,
} from "./permissionSelectorRows";
import { useGroupTransitionKeys } from "./useGroupTransitionKeys";

interface PermissionSelectorProps {
  appKey: string;
  groups: ScopedPermissionGroupItem[];
  ungroupedPermissions: ScopedPermissionItem[];
  selectedKeys: string[];
  /**
   * 所选权限组已覆盖的权限范围: 与直接勾选一起构成展示态, 但不参与直接权限提交。
   * 取消勾选其中一项会把权限组落地成逐项直接申请(见 accessRequestActions)。
   */
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
  // 两个方向各自维护过渡集合, 都在渲染期同步推进(见 useGroupTransitionKeys)。
  const exitingGroupKeys = useGroupTransitionKeys(expandedGroupKeys, "exiting");
  const enteringGroupKeys = useGroupTransitionKeys(expandedGroupKeys, "entering");
  const stableSelectedKeys = useStableStringList(selectedKeys);
  const stableCoveredKeys = useStableStringList(coveredKeys);
  const coveredKeySet = useMemo(() => new Set(stableCoveredKeys), [stableCoveredKeys]);
  // 展示态 = 直接勾选 ∪ 权限组覆盖; 提交载荷仍只用直接勾选(selectedKeys)。
  const displaySelectedKeys = useMemo(
    () => Array.from(new Set([...stableSelectedKeys, ...stableCoveredKeys])),
    [stableCoveredKeys, stableSelectedKeys],
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
  const changePermissionScope = useStableHandler(onPermissionScopeChange);
  const changePermissionGroupScope = useStableHandler(onPermissionGroupScopeChange);
  const toggleGroup = useStableHandler(onToggleGroup);
  const columns = useMemo<ColumnDef<PermissionSelectorRow>[]>(
    () =>
      permissionSelectorColumns({
        t,
        locale,
        displaySelectedKeys,
        coveredKeySet,
        onPermissionScopeChange: changePermissionScope,
        onPermissionGroupScopeChange: changePermissionGroupScope,
        onToggleGroup: toggleGroup,
      }),
    [changePermissionGroupScope, changePermissionScope, coveredKeySet, displaySelectedKeys, locale, t, toggleGroup],
  );
  // 不挂 getPaginationRowModel: 权限目录整棵树一次渲染完, 由表格容器纵向滚动。
  const table = useReactTable({
    data: displayRows,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.id,
  });

  const placeholder = selectorPlaceholder({ appKey, loading, errorMessage, isEmpty: rows.length === 0 }, t);
  if (placeholder) {
    return (
      <div className="permission-selector__surface">
        <EmptyState title={placeholder.title} description={placeholder.description} />
      </div>
    );
  }

  // 表格不分页, 工具栏因此作用于当前渲染出来的全部行(展开的权限组 + 未折叠的权限)。
  // 工具栏交上去的选择键里可以带上权限组已覆盖的范围: 去重与"落地权限组"都由选择动作统一负责。
  const visibleRows = table.getRowModel().rows;

  return (
    <div className="permission-selector__surface">
      <PermissionSelectorToolbar
        selectedCount={selectedKeys.length}
        showSelectedOnly={showSelectedOnly}
        onShowSelectedOnlyChange={setShowSelectedOnly}
        onExpandAll={() => onExpandGroups(currentPageGroupKeysFromRows(visibleRows))}
        onCollapseAll={() => onCollapseGroups(currentPageGroupKeysFromRows(visibleRows))}
        onSelectAll={() => onSelectPermissionKeys(currentPageSelectionKeysFromRows(visibleRows))}
        onSelectScope={(scopeKey) => onSelectPermissionKeys(currentPageSelectionKeysFromRows(visibleRows, scopeKey))}
        onClear={() => onClearPermissionKeys(currentPageSelectionKeysFromRows(visibleRows))}
      />
      <PermissionSelectorTable
        table={table}
        disabled={disabled}
        showSelectedOnly={showSelectedOnly}
        onToggleGroup={toggleGroup}
      />
    </div>
  );
}

/** 表格子组件内部继续用 flexRender 渲染 `<table aria-label={t("selector.ariaLabel")}>`。 */
/** 工具栏子组件内部保留 `role="switch"` 与 `aria-label={t("selector.toolbar.showSelectedOnly")}`。 */

/*
 * 列定义的输入必须只在真正变化时才换身份。
 *
 * TanStack 的 columnDef.cell 是函数组件, flexRender 直接把它当组件类型渲染: 列定义一重建,
 * React 就把每一格的子树当成"换了组件"整体卸载重挂, 表格里的按钮与勾选框全部换成新 DOM 节点。
 * 上游每次渲染都会新建 coveredKeys(派生数组)与三个回调(每次渲染重建的 actions),
 * 因此若直接用它们做 useMemo 依赖, 任何一次无关渲染都会把节点换掉 ——
 * 正落在用户按下与松开之间的那一次, 点击就丢了。
 */
function useStableStringList(list: string[]): string[] {
  const stableList = useRef(list);
  if (!stringListsAreEqual(stableList.current, list)) {
    stableList.current = list;
  }
  return stableList.current;
}

function stringListsAreEqual(left: string[], right: string[]): boolean {
  return left.length === right.length && left.every((item, index) => item === right[index]);
}

/** 身份稳定的事件回调: 调用时取最新的那个实现。 */
function useStableHandler<Args extends unknown[]>(handler: (...args: Args) => void): (...args: Args) => void {
  const latestHandler = useRef(handler);
  useEffect(() => {
    latestHandler.current = handler;
  }, [handler]);
  return useCallback((...args: Args) => latestHandler.current(...args), []);
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
