import type { Dispatch, SetStateAction } from "react";

import { Button } from "../../../../components/Button";
import { Field, SelectInput, TextArea, TextInput } from "../../../../components/Field";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AuthorizationGroupForm } from "./grantFormUpdates";

export function AuthorizationGroupFields({
  form,
  setForm,
  canManage,
}: {
  form: AuthorizationGroupForm;
  setForm: Dispatch<SetStateAction<AuthorizationGroupForm>>;
  canManage: boolean;
}) {
  const { t } = useI18n();

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Field label={t("console.matrix.field.key")}>
          <TextInput value={form.key} onChange={(event) => setForm((current) => ({ ...current, key: event.currentTarget.value }))} />
        </Field>
        <Field label={t("console.matrix.field.name")}>
          <TextInput value={form.name} onChange={(event) => setForm((current) => ({ ...current, name: event.currentTarget.value }))} />
        </Field>
        <Field label={t("console.matrix.field.kind")}>
          <SelectInput value={form.kind} onChange={(event) => setForm((current) => ({ ...current, kind: event.currentTarget.value }))}>
            <option value="role">{t("console.matrix.kindOption.role")}</option>
            <option value="bundle">{t("console.matrix.kindOption.bundle")}</option>
          </SelectInput>
        </Field>
        <Field label={t("common.status")}>
          <div className="flex flex-wrap gap-3">
            <Button type="button" variant="ghost" disabled={!canManage} onClick={() => setForm((current) => ({ ...current, requestable: !current.requestable }))}>
              {form.requestable ? t("console.matrix.setNotRequestable") : t("console.matrix.setRequestable")}
            </Button>
            <Button type="button" variant="ghost" disabled={!canManage} onClick={() => setForm((current) => ({ ...current, is_active: !current.is_active }))}>
              {form.is_active ? t("common.disable") : t("common.enable")}
            </Button>
          </div>
        </Field>
      </div>
      <Field label={t("common.description")}>
        <TextArea value={form.description ?? ""} onChange={(event) => setForm((current) => ({ ...current, description: event.currentTarget.value }))} />
      </Field>
    </PanelSurface>
  );
}
