import { useEffect, useState, type FormEvent } from "react";

import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, TextArea, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import { APP_ALIAS_MAX_LENGTH } from "../../../../lib/appDisplayName";
import type { AppSummary } from "../../../../lib/domain";
import type { AppPatchPayload } from "./overviewModel";

export function AppBasicInfoDialog({
  app,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  app?: AppSummary;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: AppPatchPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(app?.name ?? "");
  const [alias, setAlias] = useState(app?.alias ?? "");
  const [description, setDescription] = useState(app?.description ?? "");

  useEffect(() => {
    setName(app?.name ?? "");
    setAlias(app?.alias ?? "");
    setDescription(app?.description ?? "");
  }, [app?.alias, app?.description, app?.name]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit({
      name: name.trim(),
      alias: alias.trim(),
      description: description.trim(),
    });
  };

  return (
    <Dialog
      title={t("console.overview.editBasicInfoTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="app-basic-info-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="app-basic-info-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("console.overview.field.appAlias")} hint={t("console.overview.aliasHint")}>
          <TextInput
            value={alias}
            maxLength={APP_ALIAS_MAX_LENGTH}
            placeholder={t("console.overview.aliasPlaceholder")}
            onChange={(event) => setAlias(event.currentTarget.value)}
          />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.overview.saveFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
