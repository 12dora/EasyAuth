import { skipToken, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { useToast } from "../../components/ui/Toast";
import type { GrantSubmission } from "../../features/grantForm";
import { useI18n } from "../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import {
  parseDepartmentGrantPolicies,
  parseDepartmentTree,
  type DepartmentGrantPolicy,
  type DepartmentTree,
} from "../../lib/domain/departmentGrants";

/**
 * 组织授权页的数据编排。
 *
 * 授权继承是全树可见的(公司级策略出现在每一个部门), 因此任何写操作之后都按
 * ["console","departments"] 前缀整体失效, 不能只刷新当前部门 —— 下游部门的继承行同样变了。
 */
export const DEPARTMENTS_QUERY_PREFIX = ["console", "departments"];
export const DEPARTMENT_TREE_QUERY_KEY = ["console", "departments", "tree"];
const DEPARTMENT_GRANT_MUTATION_SCOPE = { id: "console-department-grants" };

export interface DepartmentGrantEditorState {
  /** null 表示新建; 非空表示编辑该策略(继承行编辑的是它定义所在部门的策略)。 */
  policy: DepartmentGrantPolicy | null;
}

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
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();

  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [expandedDeptIds, setExpandedDeptIds] = useState<string[]>([]);
  const [treeFilter, setTreeFilter] = useState("");
  const [editor, setEditor] = useState<DepartmentGrantEditorState | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DepartmentGrantPolicy | null>(null);

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

  const policiesQuery = useQuery({
    queryKey: [...DEPARTMENTS_QUERY_PREFIX, selectedDeptId, "grant-policies"],
    queryFn:
      tree && selectedDeptId
        ? async ({ signal }) =>
            parseDepartmentGrantPolicies(
              await apiRequest<unknown>(grantPoliciesUrl(tree, selectedDeptId), { signal }),
            )
        : skipToken,
    retry: false,
  });

  const invalidateDepartments = () => {
    void queryClient.invalidateQueries({ queryKey: DEPARTMENTS_QUERY_PREFIX });
  };

  const saveMutation = useMutation({
    scope: DEPARTMENT_GRANT_MUTATION_SCOPE,
    mutationFn: ({
      policyId,
      submission,
      deptId,
      sourceSlug,
      corpId,
    }: {
      policyId: number | null;
      submission: GrantSubmission;
      deptId: string;
      sourceSlug: string;
      corpId: string;
    }) => {
      if (policyId === null) {
        return apiRequest(`/console/api/v1/departments/${encodeURIComponent(deptId)}/grant-policies`, {
          method: "POST",
          body: { ...submission, source_slug: sourceSlug, corp_id: corpId } satisfies JsonObject,
        });
      }
      return apiRequest(`/console/api/v1/department-grant-policies/${policyId}`, {
        method: "PUT",
        body: { ...submission } satisfies JsonObject,
      });
    },
    onSuccess: (_payload, variables) => {
      setEditor(null);
      toast.success(t(variables.policyId === null ? "departmentGrants.toast.created" : "departmentGrants.toast.updated"));
      invalidateDepartments();
    },
  });

  const deleteMutation = useMutation({
    scope: DEPARTMENT_GRANT_MUTATION_SCOPE,
    mutationFn: (policy: DepartmentGrantPolicy) =>
      apiRequest(`/console/api/v1/department-grant-policies/${policy.id}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      toast.success(t("departmentGrants.toast.deleted"));
      invalidateDepartments();
    },
    onError: (error: Error) => {
      toast.error(t("departmentGrants.delete.failed"), error.message);
    },
  });

  return {
    treeQuery,
    tree,
    policiesQuery,
    department: policiesQuery.data?.department,
    policies: policiesQuery.data?.items ?? [],
    selectedDeptId,
    selectDepartment: setSelectedDeptId,
    expandedDeptIds,
    setExpandedDeptIds,
    treeFilter,
    setTreeFilter,
    editor,
    openEditor: (policy: DepartmentGrantPolicy | null) => {
      saveMutation.reset();
      setEditor({ policy });
    },
    closeEditor: () => setEditor(null),
    deleteTarget,
    setDeleteTarget,
    saveMutation,
    deleteMutation,
    submitEditor: (submission: GrantSubmission) => {
      if (!tree || !editor || !selectedDeptId) {
        return;
      }
      saveMutation.mutate({
        policyId: editor.policy ? editor.policy.id : null,
        submission,
        deptId: selectedDeptId,
        sourceSlug: tree.source_slug,
        corpId: tree.corp_id,
      });
    },
  };
}
