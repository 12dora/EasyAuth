import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../lib/api";
import { parseDepartmentTree, type OrgTreeNode } from "../../lib/domain/departmentGrants";

export const DEPARTMENTS_QUERY_PREFIX = ["console", "departments"];
export const DEPARTMENT_TREE_QUERY_KEY = ["console", "departments", "tree"];

/** 从根到该部门的层级; 部门不在树里时为空数组。右栏标题据此在载荷到达之前就能显示。 */
export function departmentPathTo(root: OrgTreeNode, deptId: string): OrgTreeNode[] {
  const walk = (node: OrgTreeNode, trail: OrgTreeNode[]): OrgTreeNode[] | null => {
    const path = [...trail, node];
    if (node.dept_id === deptId) {
      return path;
    }
    for (const child of node.children) {
      const found = walk(child, path);
      if (found) {
        return found;
      }
    }
    return null;
  };

  return walk(root, []) ?? [];
}

export function useDepartmentTree() {
  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [expandedDeptIds, setExpandedDeptIds] = useState<string[]>([]);
  const [treeFilter, setTreeFilter] = useState("");

  const treeQuery = useQuery({
    queryKey: DEPARTMENT_TREE_QUERY_KEY,
    queryFn: async ({ signal }) =>
      parseDepartmentTree(await apiRequest<unknown>("/console/api/v1/departments/tree", { signal })),
    // 契约错误与 409 未同步都不是瞬时故障: 重试只会把错误页面拖成一直"正在加载", 让人以为在转圈。
    retry: false,
  });
  const tree = treeQuery.data;

  // 根部门默认选中并展开; 之后完全由用户操作决定。
  useEffect(() => {
    if (!tree) {
      return;
    }
    setSelectedDeptId((current) => current || tree.root.dept_id);
    setExpandedDeptIds((current) => (current.length > 0 ? current : [tree.root.dept_id]));
  }, [tree]);

  const selectedPath = useMemo(
    () => (tree ? departmentPathTo(tree.root, selectedDeptId) : []),
    [tree, selectedDeptId],
  );

  return {
    treeQuery,
    tree,
    selectedDeptId,
    selectDepartment: setSelectedDeptId,
    expandedDeptIds,
    setExpandedDeptIds,
    treeFilter,
    setTreeFilter,
    selectedPath,
  };
}
