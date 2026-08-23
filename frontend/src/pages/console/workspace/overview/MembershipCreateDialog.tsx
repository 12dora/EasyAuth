import { useState, type FormEvent } from "react";

import { Button } from "../../../../components/Button";
import { Dialog } from "../../../../components/Dialog";
import { Field, SelectInput, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { MembershipCreatePayload, MembershipRole } from "./overviewModel";

export function MembershipCreateDialog({
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (payload: MembershipCreatePayload) => void;
}) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<MembershipRole>("developer");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedUserId = userId.trim();
    if (!normalizedUserId) {
      return;
    }
    onSubmit({ user_id: normalizedUserId, role });
    setUserId("");
  };

  return (
    <Dialog
      title={t("console.overview.createMemberTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="membership-create-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id="membership-create-form" className="grid gap-4" onSubmit={submit}>
        <Field label={t("console.overview.memberUserId")}>
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} required />
        </Field>
        <Field label={t("console.overview.memberRole")}>
          <SelectInput value={role} onChange={(event) => setRole(event.currentTarget.value as MembershipRole)}>
            <option value="developer">{t("console.overview.roleOption.developer")}</option>
            <option value="owner">{t("console.overview.roleOption.owner")}</option>
          </SelectInput>
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.overview.addMemberFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
