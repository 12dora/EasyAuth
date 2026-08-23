import { useCallback, useState } from "react";
import type { FormEvent, ReactNode } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, TextArea } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { useI18n } from "../../../i18n/I18nProvider";

export function ReasonActionDialog({
  title,
  description,
  confirmLabel,
  errorTitle,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  title: string;
  description: ReactNode;
  confirmLabel: string;
  errorTitle: string;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (reason: string) => void;
}) {
  const { t } = useI18n();
  const [reason, setReason] = useState("");
  const [fieldError, setFieldError] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedReason = reason.trim();
    if (normalizedReason === "") {
      setFieldError(t("console.operations.reasonRequired"));
      return;
    }
    onSubmit(normalizedReason);
  };
  const close = useCallback(() => {
    if (!isSubmitting) {
      onClose();
    }
  }, [isSubmitting, onClose]);

  return (
    <Dialog
      title={title}
      onClose={close}
      footer={
        <>
          <Button type="button" onClick={close} disabled={isSubmitting}>
            {t("common.cancel")}
          </Button>
          <Button form="operation-reason-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <form id="operation-reason-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{description}</p>
        <Field label={t("portal.column.reason")} error={fieldError}>
          <TextArea
            value={reason}
            maxLength={1000}
            disabled={isSubmitting}
            onChange={(event) => {
              setReason(event.currentTarget.value);
              if (fieldError && event.currentTarget.value.trim() !== "") {
                setFieldError("");
              }
            }}
          />
        </Field>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={errorTitle} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
