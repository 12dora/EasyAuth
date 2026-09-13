import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "../../components/ui/Toast";
import type { GrantSubmission } from "../../features/grantForm";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { DepartmentGrantPolicy, DepartmentTree } from "../../lib/domain/departmentGrants";
import { DEPARTMENTS_QUERY_PREFIX } from "./useDepartmentTree";

const DEPARTMENT_GRANT_MUTATION_SCOPE = { id: "console-department-grants" };

export interface DepartmentGrantEditorState {
  /** null 表示新建; 非空表示编辑该策略(继承行编辑的是它定义所在部门的策略)。 */
  policy: DepartmentGrantPolicy | null;
}

export function useDepartmentGrantMutations({
  tree,
  selectedDeptId,
  isCurrentPolicy,
  policiesAreCurrent,
}: {
  tree: DepartmentTree | undefined;
  selectedDeptId: string;
  isCurrentPolicy: (policy: DepartmentGrantPolicy) => boolean;
  policiesAreCurrent: boolean;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [editor, setEditor] = useState<DepartmentGrantEditorState | null>(null);
  const [deleteTarget, setDeleteTargetState] = useState<DepartmentGrantPolicy | null>(null);

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
      setDeleteTargetState(null);
      toast.success(t("departmentGrants.toast.deleted"));
      invalidateDepartments();
    },
    onError: (error: Error) => {
      toast.error(t("departmentGrants.delete.failed"), error.message);
    },
  });

  return {
    editor,
    openEditor: (policy: DepartmentGrantPolicy | null) => {
      if (!policiesAreCurrent || (policy && !isCurrentPolicy(policy))) {
        return;
      }
      saveMutation.reset();
      setEditor({ policy });
    },
    closeEditor: () => setEditor(null),
    deleteTarget,
    setDeleteTarget: (policy: DepartmentGrantPolicy | null) => {
      if (policy && !isCurrentPolicy(policy)) {
        return;
      }
      setDeleteTargetState(policy);
    },
    saveMutation,
    deleteMutation,
    /** policyId 为空即新建; 弹窗在新建态载入了本部门已有策略时会带上它的 id, 提交即更新那一条。 */
    submitEditor: (submission: GrantSubmission, policyId: number | null) => {
      if (!tree || !editor || !selectedDeptId) {
        return;
      }
      saveMutation.mutate({
        policyId,
        submission,
        deptId: selectedDeptId,
        sourceSlug: tree.source_slug,
        corpId: tree.corp_id,
      });
    },
  };
}
