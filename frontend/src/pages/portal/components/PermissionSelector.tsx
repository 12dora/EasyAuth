import { getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useMemo, useRef, useState } from "react";
import { EmptyState } from "../../../components/ui/EmptyState";
import { useI18n } from "../../../i18n/I18nProvider";
import type { Translator } from "../../../lib/status";

import type { ScopedPermissionGroupItem, ScopedPermissionItem } from "../hooks/accessRequestTypes";
import { PermissionSelectorTable } from "./PermissionSelectorTable";
import { PermissionSelectorToolbar } from "./PermissionSelectorToolbar";
import { PERMISSION_SELECTOR_COLUMNS } from "./permissionSelectorColumns";
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
  // 不挂 getPaginationRowModel: 权限目录整棵树一次渲染完, 由表格容器纵向滚动。
  // 列定义是模块级常量, 会变的状态全走 meta: 勾选一下只换 data 与 meta, 不重建列。
  const table = useReactTable({
    data: displayRows,
    columns: PERMISSION_SELECTOR_COLUMNS,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.id,
    meta: {
      t,
      locale,
      displaySelectedKeys,
      coveredKeySet,
      showSelectedOnly,
      disabled,
      onPermissionScopeChange,
      onPermissionGroupScopeChange,
      onToggleGroup,
    },
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
      <PermissionSelectorTable table={table} />
    </div>
  );
}

/** 表格子组件内部继续用 flexRender 渲染 `<table aria-label={t("selector.ariaLabel")}>`。 */
/** 工具栏子组件内部保留 `role="switch"` 与 `aria-label={t("selector.toolbar.showSelectedOnly")}`。 */

/*
 * 上游每次渲染都会新建 selectedKeys / coveredKeys(派生数组), 直接拿来做 useMemo 依赖,
 * 任何一次无关渲染都会重建整棵行树、白跑一遍 TanStack 行模型。这里按内容复用数组,
 * 让行树只在选择态真的变化时重建。
 *
 * 单元格 DOM 的稳定不再依赖这里: 列定义已经是模块级常量(见 permissionSelectorColumns.tsx)。
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
