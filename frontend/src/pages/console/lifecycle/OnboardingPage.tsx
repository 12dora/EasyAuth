import { Plus, RefreshCcw, UserPlus } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../components/Button";
import { PageHeader } from "../../../components/PageHeader";
import { StatusBanner } from "../../../components/StatusBanner";
import { PageState } from "../../../components/ui/PageState";
import { useI18n } from "../../../i18n/I18nProvider";
import { OnboardDialog } from "./OnboardingOnboardDialog";
import { TemplateEditorDialog } from "./OnboardingTemplateEditorDialog";
import { OnboardingTemplateTable } from "./OnboardingTemplateTable";
import { useOnboardingTemplates } from "./useOnboardingTemplates";

export function OnboardingPage() {
  const { t } = useI18n();
  const [onboardOpen, setOnboardOpen] = useState(false);
  const page = useOnboardingTemplates();
  const { templatesQuery, templates, editorState } = page;

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={t("nav.console.onboarding")}
        description={t("onboarding.description")}
        actions={
          <>
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.refresh")}
            </Button>
            <Button type="button" icon={<Plus size={16} />} onClick={() => page.openEditor(null)}>
              {t("onboarding.templates.create")}
            </Button>
            <Button type="button" variant="primary" icon={<UserPlus size={16} />} onClick={() => setOnboardOpen(true)}>
              {t("onboarding.onboard.action")}
            </Button>
          </>
        }
      />
      {templatesQuery.error && templates.length > 0 ? (
        <StatusBanner live="alert" tone="signal" title={t("onboarding.templates.loadFailed")} message={(templatesQuery.error as Error).message} />
      ) : null}
      {templatesQuery.error && templates.length === 0 ? (
        <PageState
          tone="signal"
          title={t("onboarding.templates.loadFailed")}
          description={(templatesQuery.error as Error).message}
          action={
            <Button icon={<RefreshCcw size={16} />} loading={templatesQuery.isFetching} onClick={() => void templatesQuery.refetch()}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (
        <section className="space-y-3">
          <h2 className="text-base font-semibold text-ink">{t("onboarding.templates.title")}</h2>
          <OnboardingTemplateTable
            templates={templates}
            isLoading={templatesQuery.isLoading}
            actions={{
              onEdit: page.openEditor,
              onToggle: (template) => page.toggleMutation.mutate(template),
              toggling: page.toggleMutation.isPending,
            }}
          />
        </section>
      )}
      {editorState ? (
        <TemplateEditorDialog
          template={editorState.template}
          errorMessage={page.saveMutation.error ? (page.saveMutation.error as Error).message : ""}
          isSubmitting={page.saveMutation.isPending}
          onClose={page.closeEditor}
          onSubmit={(payload) => page.saveMutation.mutate({ template: editorState.template, payload })}
        />
      ) : null}
      {onboardOpen ? (
        <OnboardDialog templates={templates.filter((template) => template.is_active)} onClose={() => setOnboardOpen(false)} />
      ) : null}
    </>
  );
}
