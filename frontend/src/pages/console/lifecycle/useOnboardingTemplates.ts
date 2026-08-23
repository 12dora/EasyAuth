import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useToast } from "../../../components/ui/Toast";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest, itemsFromPayload } from "../../../lib/api";
import type { JsonObject, ListPayload } from "../../../lib/api";
import type { OnboardingTemplateRow } from "../../../lib/domain";
import { templateRequestBody, type TemplateFormPayload } from "./onboardingTemplateModel";

const TEMPLATES_QUERY_KEY = ["console", "onboarding-templates"];

/** 入职模板列表的装载、保存与启停。 */
export function useOnboardingTemplates() {
  const { t } = useI18n();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [editorState, setEditorState] = useState<{ template: OnboardingTemplateRow | null } | null>(null);

  const templatesQuery = useQuery({
    queryKey: TEMPLATES_QUERY_KEY,
    queryFn: () => apiRequest<ListPayload<OnboardingTemplateRow>>("/console/api/v1/lifecycle/onboarding-templates"),
  });
  const templates = itemsFromPayload<OnboardingTemplateRow>(templatesQuery.data);

  const saveMutation = useMutation({
    mutationFn: ({ template, payload }: { template: OnboardingTemplateRow | null; payload: TemplateFormPayload }) => {
      const body = templateRequestBody(payload);
      if (template) {
        return apiRequest(`/console/api/v1/lifecycle/onboarding-templates/${template.id}`, { method: "PATCH", body });
      }
      return apiRequest("/console/api/v1/lifecycle/onboarding-templates", { method: "POST", body });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY });
      setEditorState(null);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (template: OnboardingTemplateRow) =>
      apiRequest(`/console/api/v1/lifecycle/onboarding-templates/${template.id}`, {
        method: "PATCH",
        body: { is_active: !template.is_active } satisfies JsonObject,
      }),
    onSuccess: (_, template) => {
      void queryClient.invalidateQueries({ queryKey: TEMPLATES_QUERY_KEY });
      // template.is_active 是切换前的旧值。
      // 旧值为启用即刚被停用，反之亦然。
      toast.success(
        template.is_active ? t("onboarding.templates.disableSuccess") : t("onboarding.templates.enableSuccess"),
      );
    },
    onError: (error: Error) => {
      toast.error(t("onboarding.templates.toggleFailed"), error.message);
    },
  });

  return {
    templatesQuery,
    templates,
    editorState,
    openEditor: (template: OnboardingTemplateRow | null) => {
      saveMutation.reset();
      setEditorState({ template });
    },
    closeEditor: () => setEditorState(null),
    saveMutation,
    toggleMutation,
  };
}
