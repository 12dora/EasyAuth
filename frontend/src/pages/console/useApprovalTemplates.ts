import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "../../components/ui/Toast";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../lib/api";
import type { ListPayload } from "../../lib/api";
import type { ApprovalTemplateItem } from "../../lib/domain";
import {
  TEMPLATES_QUERY_KEY,
  TEMPLATE_MUTATION_SCOPE,
  templateCreateBody,
  templatePatchBody,
  type ApprovalTemplatePayload,
  type TemplateFormPayload,
} from "./approvalTemplateModel";

/** 审批模板列表的装载、保存与删除。 */
export function useApprovalTemplates() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [editorState, setEditorState] = useState<{ template: ApprovalTemplateItem | null } | null>(null);
  const [testTemplate, setTestTemplate] = useState<ApprovalTemplateItem | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ApprovalTemplateItem | null>(null);

  const templatesQuery = useQuery({
    queryKey: TEMPLATES_QUERY_KEY,
    queryFn: ({ signal }) =>
      apiRequest<ListPayload<ApprovalTemplateItem>>("/console/api/v1/approval-templates", { signal }),
  });
  const templates = itemsFromPayload<ApprovalTemplateItem>(templatesQuery.data);

  const applyTemplatePayload = async (payload: ApprovalTemplatePayload) => {
    await queryClient.cancelQueries({ queryKey: TEMPLATES_QUERY_KEY, exact: true });
    queryClient.setQueryData<ListPayload<ApprovalTemplateItem>>(TEMPLATES_QUERY_KEY, (current) => {
      const currentItems = current?.data ?? [];
      const existingIndex = currentItems.findIndex((item) => item.id === payload.approval_template.id);
      return {
        ...current,
        data:
          existingIndex === -1
            ? [...currentItems, payload.approval_template]
            : currentItems.map((item) =>
                item.id === payload.approval_template.id ? payload.approval_template : item,
              ),
      };
    });
    void queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY, exact: true });
  };

  const deleteMutation = useMutation({
    scope: TEMPLATE_MUTATION_SCOPE,
    mutationFn: (template: ApprovalTemplateItem) =>
      apiRequest(`/console/api/v1/approval-templates/${template.id}`, { method: "DELETE" }),
    onSuccess: async (_payload, template) => {
      await queryClient.cancelQueries({ queryKey: TEMPLATES_QUERY_KEY, exact: true });
      queryClient.setQueryData<ListPayload<ApprovalTemplateItem>>(TEMPLATES_QUERY_KEY, (current) => ({
        ...current,
        data: current?.data?.filter((item) => item.id !== template.id) ?? [],
      }));
      setDeleteTarget(null);
      toast.success(t("approvalTemplates.deleteSuccess"));
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY, exact: true });
    },
    onError: (error: Error) => {
      toast.error(t("approvalTemplates.deleteFailed"), error.message);
    },
  });

  const saveMutation = useMutation({
    scope: TEMPLATE_MUTATION_SCOPE,
    mutationFn: ({ template, payload }: { template: ApprovalTemplateItem | null; payload: TemplateFormPayload }) => {
      if (template) {
        return apiRequest<ApprovalTemplatePayload>(`/console/api/v1/approval-templates/${template.id}`, {
          method: "PATCH",
          body: templatePatchBody(payload),
        });
      }
      return apiRequest<ApprovalTemplatePayload>("/console/api/v1/approval-templates", {
        method: "POST",
        body: templateCreateBody(payload),
      });
    },
    onSuccess: async (payload) => {
      await applyTemplatePayload(payload);
      setEditorState(null);
    },
  });

  return {
    templatesQuery,
    templates,
    editorState,
    openEditor: (template: ApprovalTemplateItem | null) => {
      saveMutation.reset();
      setEditorState({ template });
    },
    closeEditor: () => setEditorState(null),
    testTemplate,
    setTestTemplate,
    deleteTarget,
    setDeleteTarget,
    saveMutation,
    deleteMutation,
  };
}
