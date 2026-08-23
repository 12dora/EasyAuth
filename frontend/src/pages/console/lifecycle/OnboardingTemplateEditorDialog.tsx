import { useState, type FormEvent } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, TextArea, TextInput } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { OnboardingTemplateRow } from "../../../lib/domain";
import { TemplateItemComposer } from "./OnboardingTemplateItemComposer";
import {
  templateItemDrafts,
  templateItemLine,
  type TemplateFormPayload,
  type TemplateItemDraft,
} from "./onboardingTemplateModel";

export interface TemplateEditorDialogProps {
  template: OnboardingTemplateRow | null;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TemplateFormPayload) => void;
}

export function TemplateEditorDialog({
  template,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: TemplateEditorDialogProps) {
  const { t } = useI18n();
  const [name, setName] = useState(template?.name ?? "");
  const [description, setDescription] = useState(template?.description ?? "");
  const [items, setItems] = useState<TemplateItemDraft[]>(() => templateItemDrafts(template));

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      return;
    }
    // 启用/停用已移到列表操作列。
    // 编辑弹窗只改内容，is_active 原样透传；新建默认启用。
    onSubmit({ name: normalizedName, description: description.trim(), is_active: template?.is_active ?? true, items });
  };

  return (
    <Dialog
      title={template ? t("onboarding.editor.editTitle") : t("onboarding.editor.createTitle")}
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="onboarding-template-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="onboarding-template-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} required onChange={(event) => setName(event.currentTarget.value)} />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={2} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        <Field label={t("onboarding.editor.items")} as="group">
          <div className="space-y-2">
            {items.length === 0 ? (
              <p className="text-caption text-ink-faint">{t("onboarding.editor.itemsEmpty")}</p>
            ) : (
              <ul className="grid gap-1.5">
                {items.map((item, index) => (
                  <li
                    key={`${item.app_key}-${item.kind}-${item.key}-${item.scope_key}-${index}`}
                    className="flex items-center justify-between gap-3 rounded-[3px] border border-ink/10 bg-paper-soft px-3 py-2"
                  >
                    <span className="min-w-0 text-body text-ink">
                      <code className="mr-2 text-caption text-ink-faint">{item.app_key}</code>
                      {templateItemLine(t, item)}
                    </span>
                    <Button
                      size="sm"
                      type="button"
                      variant="ghost-danger"
                      onClick={() => setItems((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    >
                      {t("onboarding.editor.removeItem")}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            <TemplateItemComposer onAdd={(item) => setItems((current) => [...current, item])} />
          </div>
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("onboarding.editor.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
