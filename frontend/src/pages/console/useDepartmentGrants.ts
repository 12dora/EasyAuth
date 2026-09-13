import { keepPreviousData, skipToken, useQuery } from "@tanstack/react-query";

import { ApiError, apiRequest } from "../../lib/api";
import {
  parseDepartmentGrantPolicies,
  type DepartmentGrantPolicy,
  type DepartmentTree,
} from "../../lib/domain/departmentGrants";
import { useDepartmentGrantMutations } from "./useDepartmentGrantMutations";
import { DEPARTMENTS_QUERY_PREFIX, DEPARTMENT_TREE_QUERY_KEY, useDepartmentTree } from "./useDepartmentTree";

export { DEPARTMENTS_QUERY_PREFIX, DEPARTMENT_TREE_QUERY_KEY };
export type { DepartmentGrantEditorState } from "./useDepartmentGrantMutations";

function grantPoliciesUrl(tree: DepartmentTree, deptId: string): string {
  const query = new URLSearchParams({ source_slug: tree.source_slug, corp_id: tree.corp_id });
  return `/console/api/v1/departments/${encodeURIComponent(deptId)}/grant-policies?${query.toString()}`;
}

/** 后端 422 的逐条中文校验信息(`details.errors`); 没有就是空数组。 */
export function apiErrorDetailMessages(error: unknown): string[] {
  if (!(error instanceof ApiError) || typeof error.details !== "object" || error.details === null) {
    return [];
  }
  const errors = (error.details as { errors?: unknown }).errors;
  return Array.isArray(errors) ? errors.filter((item): item is string => typeof item === "string") : [];
}

export function useDepartmentGrants() {
  const treeState = useDepartmentTree();
  const { tree, selectedDeptId } = treeState;

  const policiesQuery = useQuery({
    queryKey: [...DEPARTMENTS_QUERY_PREFIX, selectedDeptId, "grant-policies"],
    queryFn:
      tree && selectedDeptId
        ? async ({ signal }) =>
            parseDepartmentGrantPolicies(
              await apiRequest<unknown>(grantPoliciesUrl(tree, selectedDeptId), { signal }),
            )
        : skipToken,
    // 切部门时保留上一份数据: 右栏不再整块塌掉再弹回来, 加载态改由 isFetching 画在表格上。
    placeholderData: keepPreviousData,
    retry: false,
  });

  // 留存的数据可能还是上一个部门的; 人数与"本部门已有策略"这类口径必须等载荷对得上才算数。
  const loadedList = policiesQuery.data;
  const currentList = loadedList && loadedList.department.dept_id === selectedDeptId ? loadedList : undefined;

  /**
   * 这一行是不是当前部门这一份载荷里的。
   *
   * keepPreviousData 会让上一部门的行继续挂在表格里等新数据; antd 的加载遮罩只挡鼠标, 挡不住
   * 键盘 —— 焦点仍能落到旧行的「编辑」上。放任下去就会把上一部门的策略当成当前部门的改掉,
   * 因此所有写入入口都先认这一关。
   */
  const isCurrentPolicy = (policy: DepartmentGrantPolicy) =>
    Boolean(currentList?.items.some((item) => item.id === policy.id));

  const mutations = useDepartmentGrantMutations({
    tree,
    selectedDeptId,
    isCurrentPolicy,
    policiesAreCurrent: Boolean(currentList),
  });

  return {
    treeQuery: treeState.treeQuery,
    tree,
    policiesQuery,
    department: currentList?.department,
    policies: loadedList?.items ?? [],
    /** 当前部门的授权已经取到; 未就绪时新增与行内操作一律关闭。 */
    policiesAreCurrent: Boolean(currentList),
    /** 定义在本部门上的策略(不含继承); 新增授权时据此认出"这个应用已经授过了"。 */
    ownPolicies: currentList ? currentList.items.filter((policy) => !policy.inherited) : [],
    selectedPath: treeState.selectedPath,
    selectedDeptId,
    selectDepartment: treeState.selectDepartment,
    expandedDeptIds: treeState.expandedDeptIds,
    setExpandedDeptIds: treeState.setExpandedDeptIds,
    treeFilter: treeState.treeFilter,
    setTreeFilter: treeState.setTreeFilter,
    ...mutations,
  };
}
