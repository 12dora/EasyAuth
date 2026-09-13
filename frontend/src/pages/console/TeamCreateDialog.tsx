import type { FormEvent } from "react";
import { useState } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";

export interface TeamCreateFormPayload {
  name: string;
  description: string;
}

export function TeamCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: TeamCreateFormPayload) => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      return;
    }
    onSubmit({ name: normalizedName, description: description.trim() });
  };

  return (
    <Dialog
      title={t("console.teams.create")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="create-team-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.create")}
          </Button>
        </>
      }
    >
      <form id="create-team-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("common.name")}>
          <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} required />
        </Field>
        <Field label={t("common.description")}>
          <TextArea rows={3} value={description} onChange={(event) => setDescription(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.teams.createFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
