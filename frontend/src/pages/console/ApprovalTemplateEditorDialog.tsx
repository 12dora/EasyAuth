import { useState, type FormEvent } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import type { ApprovalTemplateItem } from "../../lib/domain";
import { initialTemplateForm, validateTemplateForm, type TemplateFormPayload } from "./approvalTemplateModel";

export function ApprovalTemplateEditorDialog({
  template,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  template: ApprovalTemplateItem | null;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TemplateFormPayload) => void;
}) {
  const { t } = useI18n();
  const initial = initialTemplateForm(template);
  const [appKey, setAppKey] = useState(initial.appKey);
  const [key, setKey] = useState(initial.key);
  const [name, setName] = useState(initial.name);
  const [processCode, setProcessCode] = useState(initial.processCode);
  const [formSchemaText, setFormSchemaText] = useState(initial.formSchemaText);
  const [formMappingText, setFormMappingText] = useState(initial.formMappingText);
  const [isActive, setIsActive] = useState(initial.isActive);
  const [schemaError, setSchemaError] = useState("");
  const [mappingError, setMappingError] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validation = validateTemplateForm(formSchemaText, formMappingText);
    if (!validation.ok) {
      if (validation.invalid === "schema") {
        setSchemaError(t("approvalTemplates.invalidFormSchema"));
        return;
      }
      setSchemaError("");
      setMappingError(t("approvalTemplates.invalidFormMapping"));
      return;
    }
    setSchemaError("");
    setMappingError("");
    onSubmit({
      app_key: appKey.trim(),
      key: key.trim(),
      name: name.trim(),
      dingtalk_process_code: processCode.trim(),
      form_schema: validation.formSchema,
      form_mapping: validation.formMapping,
      is_active: isActive,
    });
  };

  return (
    <Dialog
      title={template ? t("approvalTemplates.editTitle") : t("approvalTemplates.createTitle")}
      size="lg"
      onClose={onClose}
      closeDisabled={isSubmitting}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button form="approval-template-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="approval-template-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("approvalTemplates.field.appKey")} hint={t("approvalTemplates.field.appKeyHint")}>
          <TextInput
            value={appKey}
            disabled={Boolean(template)}
            autoComplete="off"
            onChange={(event) => setAppKey(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("approvalTemplates.field.key")} hint={t("approvalTemplates.field.keyHint")}>
          <TextInput
            value={key}
            disabled={Boolean(template)}
            required={!template}
            autoComplete="off"
            onChange={(event) => setKey(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("common.name")}>
          <TextInput value={name} required onChange={(event) => setName(event.currentTarget.value)} />
        </Field>
        <Field label={t("approvalTemplates.field.processCode")}>
          <TextInput
            value={processCode}
            required
            autoComplete="off"
            onChange={(event) => setProcessCode(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("approvalTemplates.field.formSchema")} hint={t("approvalTemplates.field.formSchemaHint")} error={schemaError}>
          <TextArea
            rows={8}
            spellCheck={false}
            className="font-mono text-caption"
            value={formSchemaText}
            onChange={(event) => {
              setFormSchemaText(event.currentTarget.value);
              if (schemaError) {
                setSchemaError("");
              }
              if (mappingError) {
                setMappingError("");
              }
            }}
          />
        </Field>
        <Field label={t("approvalTemplates.field.formMapping")} hint={t("approvalTemplates.field.formMappingHint")} error={mappingError}>
          <TextArea
            rows={8}
            spellCheck={false}
            className="font-mono text-caption"
            value={formMappingText}
            onChange={(event) => {
              setFormMappingText(event.currentTarget.value);
              if (mappingError) {
                setMappingError("");
              }
            }}
          />
        </Field>
        <label className="inline-flex items-center gap-2 text-body text-ink">
          <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.currentTarget.checked)} />
          <span>{t("approvalTemplates.field.isActive")}</span>
        </label>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("approvalTemplates.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
