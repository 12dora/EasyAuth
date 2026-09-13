import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

import { useGroupTransitionKeys } from "../../pages/portal/components/useGroupTransitionKeys";
import type { OrgTreeRuntime } from "./OrgTreeItem";
import {
  collectMatchAncestorIds,
  collectVisibleDeptIds,
  createOrgTreeRowStateStore,
  flattenRows,
  type FlatRow,
  type OrgTreeNode,
  type OrgTreeProps,
  type OrgTreeRowStateInput,
} from "./orgTreeModel";

export interface OrgTreeDerived {
  visibleDeptIds: Set<string>;
  effectiveExpandedIds: string[];
  rows: FlatRow[];
}

export function useOrgTreeDerived(
  root: OrgTreeNode,
  expandedDeptIds: string[],
  keyword: string,
  labelFor: (node: OrgTreeNode) => string,
): OrgTreeDerived {
  const visibleDeptIds = useMemo(() => collectVisibleDeptIds(root, keyword, labelFor), [root, keyword, labelFor]);
  const autoExpandedDeptIds = useMemo(
    () => collectMatchAncestorIds(root, keyword, labelFor),
    [root, keyword, labelFor],
  );
  // 过滤命中时祖先必须展开才看得到匹配项; 这是渲染期的派生值, 不回写受控状态,
  // 清空搜索后展开集合原样回到用户自己的选择。
  const effectiveExpandedIds = useMemo(
    () => [...expandedDeptIds, ...autoExpandedDeptIds.filter((deptId) => !expandedDeptIds.includes(deptId))],
    [expandedDeptIds, autoExpandedDeptIds],
  );
  const rows = useMemo(
    () => flattenRows(root, effectiveExpandedIds, visibleDeptIds),
    [root, effectiveExpandedIds, visibleDeptIds],
  );
  return { visibleDeptIds, effectiveExpandedIds, rows };
}

function useOrgTreeRowStates(rowStateInput: OrgTreeRowStateInput) {
  const [rowStates] = useState(() => createOrgTreeRowStateStore(rowStateInput));
  // 布局阶段推送: 订阅到变化的行在浏览器绘制之前就重渲染完, 选中态不会晚一帧。
  useLayoutEffect(() => {
    rowStates.update(rowStateInput);
  }, [rowStates, rowStateInput]);
  return rowStates;
}

export function useOrgTreeRuntimeValue({
  selectedDeptId,
  expandedDeptIds,
  onSelect,
  onExpandedChange,
  labelFor,
  derived,
}: {
  selectedDeptId: string;
  expandedDeptIds: string[];
  onSelect: (deptId: string) => void;
  onExpandedChange: (deptIds: string[]) => void;
  labelFor: (node: OrgTreeNode) => string;
  derived: OrgTreeDerived;
}): { runtime: OrgTreeRuntime; handleKeyDown: (event: KeyboardEvent<HTMLDivElement>) => void } {
  const { visibleDeptIds, effectiveExpandedIds, rows } = derived;
  const enteringDeptIds = useGroupTransitionKeys(effectiveExpandedIds, "entering");
  const exitingDeptIds = useGroupTransitionKeys(effectiveExpandedIds, "exiting");
  const [focusedDeptId, setFocusedDeptId] = useState("");
  const itemsByDeptId = useRef(new Map<string, HTMLDivElement>());

  // 焦点落点: 用户上次落焦的行 > 当前选中行 > 第一行。行被过滤掉或收起时自动回退。
  const activeDeptId =
    rows.find((row) => row.node.dept_id === focusedDeptId)?.node.dept_id ??
    rows.find((row) => row.node.dept_id === selectedDeptId)?.node.dept_id ??
    rows[0]?.node.dept_id ??
    "";

  // 行上的事件回调必须自始至终是同一份引用, 否则 runtime 一变整棵树都要重渲染;
  // 它们要读的最新 props 走这份 ref —— 事件只在提交之后触发, 提交后再写是安全的。
  const latestPropsRef = useRef({ expandedDeptIds, onSelect, onExpandedChange });
  useLayoutEffect(() => {
    latestPropsRef.current = { expandedDeptIds, onSelect, onExpandedChange };
  });

  const focusItem = useCallback((deptId: string) => {
    setFocusedDeptId(deptId);
    itemsByDeptId.current.get(deptId)?.focus();
  }, []);

  const setExpanded = useCallback((deptId: string, expanded: boolean) => {
    const { expandedDeptIds: current, onExpandedChange: change } = latestPropsRef.current;
    if (expanded) {
      if (!current.includes(deptId)) {
        change([...current, deptId]);
      }
      return;
    }
    change(current.filter((item) => item !== deptId));
  }, []);

  const selectRow = useCallback(
    (node: OrgTreeNode, expanded: boolean) => {
      // 鼠标点行同样是在操作这一行: 焦点跟过来, 紧接着的方向键/回车才作用在它身上。
      focusItem(node.dept_id);
      latestPropsRef.current.onSelect(node.dept_id);
      if (node.children.length > 0) {
        setExpanded(node.dept_id, !expanded);
      }
    },
    [focusItem, setExpanded],
  );

  const toggleRow = useCallback(
    (node: OrgTreeNode, expanded: boolean) => {
      focusItem(node.dept_id);
      setExpanded(node.dept_id, !expanded);
    },
    [focusItem, setExpanded],
  );

  const registerItem = useCallback((deptId: string, element: HTMLDivElement | null) => {
    if (element) {
      itemsByDeptId.current.set(deptId, element);
      return;
    }
    itemsByDeptId.current.delete(deptId);
  }, []);

  const rowStateInput = useMemo<OrgTreeRowStateInput>(
    () => ({
      selectedDeptId,
      activeDeptId,
      expandedDeptIds: effectiveExpandedIds,
      enteringDeptIds,
      exitingDeptIds,
    }),
    [selectedDeptId, activeDeptId, effectiveExpandedIds, enteringDeptIds, exitingDeptIds],
  );
  const rowStates = useOrgTreeRowStates(rowStateInput);

  const runtime = useMemo<OrgTreeRuntime>(
    () => ({
      labelFor,
      visibleDeptIds,
      rowStates,
      selectRow,
      toggleRow,
      focusRow: setFocusedDeptId,
      registerItem,
    }),
    [labelFor, visibleDeptIds, rowStates, selectRow, toggleRow, registerItem],
  );

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    handleOrgTreeKeyDown(event, {
      rows,
      activeDeptId,
      effectiveExpandedIds,
      focusItem,
      setExpanded,
      onSelect,
      setFocusedDeptId,
    });
  };

  return { runtime, handleKeyDown };
}

export function useOrgTree({
  root,
  selectedDeptId,
  expandedDeptIds,
  onSelect,
  onExpandedChange,
  filter = "",
  labelFor,
}: OrgTreeProps & { labelFor: (node: OrgTreeNode) => string }) {
  const keyword = filter.trim().toLowerCase();
  const derived = useOrgTreeDerived(root, expandedDeptIds, keyword, labelFor);
  const { runtime, handleKeyDown } = useOrgTreeRuntimeValue({
    selectedDeptId,
    expandedDeptIds,
    onSelect,
    onExpandedChange,
    labelFor,
    derived,
  });
  return {
    runtime,
    handleKeyDown,
    rootVisible: derived.visibleDeptIds.has(root.dept_id),
  };
}

function handleOrgTreeKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  {
    rows,
    activeDeptId,
    effectiveExpandedIds,
    focusItem,
    setExpanded,
    onSelect,
    setFocusedDeptId,
  }: {
    rows: FlatRow[];
    activeDeptId: string;
    effectiveExpandedIds: string[];
    focusItem: (deptId: string) => void;
    setExpanded: (deptId: string, expanded: boolean) => void;
    onSelect: (deptId: string) => void;
    setFocusedDeptId: (deptId: string) => void;
  },
) {
  const index = rows.findIndex((row) => row.node.dept_id === activeDeptId);
  if (index === -1) {
    return;
  }
  const row = rows[index];
  const deptId = row.node.dept_id;
  const hasChildren = row.node.children.length > 0;
  const expanded = effectiveExpandedIds.includes(deptId);
  const moveFocusTo = (nextDeptId: string | undefined) => {
    if (nextDeptId) {
      focusItem(nextDeptId);
    }
  };

  switch (event.key) {
    case "ArrowDown":
      event.preventDefault();
      moveFocusTo(rows[index + 1]?.node.dept_id);
      return;
    case "ArrowUp":
      event.preventDefault();
      moveFocusTo(rows[index - 1]?.node.dept_id);
      return;
    case "ArrowRight":
      event.preventDefault();
      if (!hasChildren) {
        return;
      }
      if (expanded) {
        moveFocusTo(rows[index + 1]?.node.dept_id);
        return;
      }
      setExpanded(deptId, true);
      return;
    case "ArrowLeft":
      event.preventDefault();
      if (hasChildren && expanded) {
        setExpanded(deptId, false);
        return;
      }
      moveFocusTo(row.parentDeptId || undefined);
      return;
    case "Enter":
      event.preventDefault();
      setFocusedDeptId(deptId);
      onSelect(deptId);
      return;
    default:
  }
}
