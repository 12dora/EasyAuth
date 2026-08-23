import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, SelectInput } from "../../../components/Field";
import { useToast } from "../../../components/ui/Toast";
import { UserSearchInput } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import type { JsonObject } from "../../../lib/api";
import type { OnboardResult, OnboardingTemplateRow } from "../../../lib/domain";
import { templateItemLine } from "./onboardingTemplateModel";

export function OnboardDialog({
  templates,
  onClose,
}: {
  templates: OnboardingTemplateRow[];
  onClose: () => void;
}) {
  const { t } = useI18n();
  const toast = useToast();
  const [userId, setUserId] = useState("");
  const [templateId, setTemplateId] = useState("");
  const selectedTemplate = templates.find((template) => String(template.id) === templateId);

  const onboardMutation = useMutation({
    mutationFn: () =>
      apiRequest<OnboardResult>("/console/api/v1/lifecycle/onboard", {
        method: "POST",
        body: { user_id: userId.trim(), template_id: Number(templateId) } satisfies JsonObject,
      }),
    // 入职结果即操作反馈。
    // 成功弹 toast 并关闭弹窗，失败弹 toast 保留弹窗以便修正重试。
    onSuccess: (payload) => {
      toast.success(t("onboarding.onboard.success", { count: payload.granted_app_count }));
      onClose();
    },
    onError: (error: Error) => {
      toast.error(t("onboarding.onboard.failed"), error.message);
    },
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!userId.trim() || !templateId) {
      return;
    }
    onboardMutation.mutate();
  };

  return (
    <Dialog
      title={t("onboarding.onboard.action")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.close")}
          </Button>
          <Button
            form="onboard-form"
            type="submit"
            variant="primary"
            loading={onboardMutation.isPending}
            disabled={onboardMutation.isPending || !userId.trim() || !templateId}
          >
            {t("onboarding.onboard.confirm")}
          </Button>
        </>
      }
    >
      <form id="onboard-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{t("onboarding.onboard.description")}</p>
        <Field label={t("onboarding.onboard.user")} as="group">
          <UserSearchInput value={userId} aria-label={t("onboarding.onboard.user")} onChange={setUserId} />
        </Field>
        <Field label={t("onboarding.onboard.template")}>
          <SelectInput value={templateId} onChange={(event) => setTemplateId(event.currentTarget.value)}>
            <option value="">{t("handover.transfer.templatePlaceholder")}</option>
            {templates.map((template) => (
              <option key={template.id} value={String(template.id)}>
                {template.name}
              </option>
            ))}
          </SelectInput>
        </Field>
        {selectedTemplate ? (
          <div className="space-y-2 rounded-[3px] border border-ink/10 bg-paper-soft p-3">
            <h3 className="text-caption font-semibold uppercase tracking-caps-wide text-ink-soft">
              {t("onboarding.onboard.previewTitle")}
            </h3>
            {selectedTemplate.items.length === 0 ? (
              <p className="text-caption text-ink-faint">{t("onboarding.onboard.previewEmpty")}</p>
            ) : (
              <ul className="grid gap-1 text-body text-ink">
                {selectedTemplate.items.map((item) => (
                  <li key={item.id}>
                    <code className="mr-2 text-caption text-ink-faint">{item.app_key}</code>
                    {templateItemLine(t, item)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </form>
    </Dialog>
  );
}
