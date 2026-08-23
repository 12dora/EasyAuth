import { useState } from "react";
import type { FormEvent } from "react";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserMultiSelect } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";

export function ReassignApproversDialog({
  description,
  errorMessage,
  isSubmitting,
  onClose,
  onSubmit,
}: {
  description: string;
  errorMessage: string;
  isSubmitting: boolean;
  onClose: () => void;
  onSubmit: (approverUserIds: string[]) => void;
}) {
  const { t } = useI18n();
  const [approverUserIds, setApproverUserIds] = useState<string[]>([]);
  const [fieldError, setFieldError] = useState("");

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (approverUserIds.length === 0) {
      setFieldError(t("console.accessRequests.approversRequired"));
      return;
    }
    onSubmit(approverUserIds);
  };

  return (
    <Dialog
      title={t("console.accessRequests.reassignTitle")}
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button form="reassign-approvers-form" type="submit" variant="primary" loading={isSubmitting} disabled={isSubmitting}>
            {t("console.accessRequests.reassignConfirm")}
          </Button>
        </>
      }
    >
      <form id="reassign-approvers-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{description}</p>
        <Field label={t("console.accessRequests.approversField")} error={fieldError}>
          <UserMultiSelect
            value={approverUserIds}
            onChange={(next) => {
              setApproverUserIds(next);
              if (fieldError && next.length > 0) {
                setFieldError("");
              }
            }}
            searchPurpose="approver"
          />
        </Field>
        <p className="text-xs leading-5 text-ink-faint">{t("console.accessRequests.reassignNote")}</p>
        {errorMessage ? <StatusBanner live="alert" tone="signal" title={t("console.accessRequests.reassignFailed")} message={errorMessage} /> : null}
      </form>
    </Dialog>
  );
}
