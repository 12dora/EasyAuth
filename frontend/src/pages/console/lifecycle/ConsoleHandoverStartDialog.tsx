import { useState, type FormEvent } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, TextArea } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverStartTarget } from "./consolePeopleModel";

export function ConsoleHandoverStartDialog({
  target,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  target: HandoverStartTarget;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const isOffboard = target.kind === "offboard";
  const personName = target.person.name || target.person.user_id;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSubmit(reason.trim());
  };

  return (
    <Dialog
      title={isOffboard ? t("people.startDialog.offboardTitle") : t("people.startDialog.transferTitle")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="handover-start-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("people.startDialog.confirm")}
          </Button>
        </>
      }
    >
      <form id="handover-start-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">
          {isOffboard
            ? t("people.startDialog.offboardMessage", { name: personName })
            : t("people.startDialog.transferMessage", { name: personName })}
        </p>
        <Field label={t("people.startDialog.reason")} hint={t("people.startDialog.reasonHint")}>
          <TextArea rows={3} value={reason} onChange={(event) => setReason(event.currentTarget.value)} />
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("people.startFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
