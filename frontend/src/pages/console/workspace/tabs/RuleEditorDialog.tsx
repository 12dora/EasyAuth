import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { UserMultiSelect } from "../../../../components/UserSelect";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { RuleFormState } from "./rulesTabModel";

export function RuleEditorDialog({
  editingRuleId,
  form,
  isSaving,
  onClose,
  onFormChange,
  onSubmit,
}: {
  editingRuleId: number | null;
  form: RuleFormState;
  isSaving: boolean;
  onClose: () => void;
  onFormChange: (next: RuleFormState) => void;
  onSubmit: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog
      title={editingRuleId ? t("console.rules.editTitle") : t("console.rules.createTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            form="approval-rule-form"
            type="submit"
            variant="primary"
            loading={isSaving}
            disabled={!form.target_key || form.approverUserIds.length === 0 || isSaving}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form
        id="approval-rule-form"
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <Field label={t("console.rules.targetTypeLabel")}>
          <SelectInput
            aria-label={t("console.rules.targetTypeLabel")}
            value={form.target_type}
            onChange={(event) => {
              const targetType = event.currentTarget.value as RuleFormState["target_type"];
              onFormChange({ ...form, target_type: targetType });
            }}
          >
            <option value="authorization_group">{t("console.rules.targetOption.authorizationGroup")}</option>
            <option value="permission">{t("console.rules.targetOption.permission")}</option>
          </SelectInput>
        </Field>
        <Field label={t("console.rules.targetKey")}>
          <TextInput
            aria-label={t("console.rules.targetKey")}
            value={form.target_key}
            onChange={(event) => {
              const targetKey = event.currentTarget.value;
              onFormChange({ ...form, target_key: targetKey });
            }}
          />
        </Field>
        <Field label={t("console.rules.approverField")} hint={t("console.rules.approverHint")}>
          <UserMultiSelect
            aria-label={t("console.rules.approverField")}
            value={form.approverUserIds}
            onChange={(approverUserIds) => onFormChange({ ...form, approverUserIds })}
            searchPurpose="approver"
          />
        </Field>
      </form>
    </Dialog>
  );
}
