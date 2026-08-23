import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { UserSearchInput } from "../../components/UserSelect";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { JsonObject } from "../../lib/api";
import type { ApprovalTemplateItem, ApprovalTemplateTestResult } from "../../lib/domain";
import { approvalStatusLabel } from "../../lib/status";
import { validateTemplateTest } from "./approvalTemplateModel";

interface TestFieldErrors {
  originator: string;
  appKey: string;
  form: string;
}

const NO_TEST_ERRORS: TestFieldErrors = { originator: "", appKey: "", form: "" };

export function ApprovalTemplateTestDialog({
  template,
  onClose,
}: {
  template: ApprovalTemplateItem;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [originatorUserId, setOriginatorUserId] = useState("");
  const [appKey, setAppKey] = useState("");
  const [formText, setFormText] = useState("");
  const [errors, setErrors] = useState<TestFieldErrors>(NO_TEST_ERRORS);
  const isPlatformTemplate = template.app_key === "";
  const testMutation = useMutation({
    mutationFn: (body: JsonObject) =>
      apiRequest<ApprovalTemplateTestResult>(`/console/api/v1/approval-templates/${template.id}/test`, {
        method: "POST",
        body,
      }),
  });
  const result = testMutation.data;

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const validation = validateTemplateTest({ originatorUserId, appKey, formText, isPlatformTemplate });
    if (!validation.ok) {
      setErrors((current) => ({
        originator: validation.originatorMissing ? t("approvalTemplates.test.originatorRequired") : current.originator,
        appKey: validation.appKeyMissing ? t("approvalTemplates.test.appKeyRequired") : current.appKey,
        form: validation.formInvalid ? t("approvalTemplates.invalidJson") : current.form,
      }));
      return;
    }
    testMutation.mutate(validation.body);
  };

  const clearError = (field: keyof TestFieldErrors) => {
    setErrors((current) => (current[field] === "" ? current : { ...current, [field]: "" }));
  };

  return (
    <Dialog
      title={t("approvalTemplates.test.action")}
      eyebrow={<code>{template.key}</code>}
      onClose={onClose}
      closeDisabled={testMutation.isPending}
      footer={
        <>
          <Button type="button" onClick={onClose} disabled={testMutation.isPending}>
            {t("common.close")}
          </Button>
          <Button
            form="approval-template-test-form"
            type="submit"
            variant="primary"
            loading={testMutation.isPending}
            disabled={testMutation.isPending}
          >
            {t("approvalTemplates.test.submit")}
          </Button>
        </>
      }
    >
      <form id="approval-template-test-form" className="grid gap-4" onSubmit={submit}>
        <p className="text-body leading-5 text-ink-soft">{t("approvalTemplates.test.description")}</p>
        <Field label={t("approvalTemplates.test.originator")} error={errors.originator} as="group">
          <UserSearchInput
            value={originatorUserId}
            aria-label={t("approvalTemplates.test.originator")}
            onChange={(next) => {
              setOriginatorUserId(next);
              if (next.trim() !== "") {
                clearError("originator");
              }
            }}
          />
        </Field>
        {isPlatformTemplate ? (
          <Field label={t("approvalTemplates.test.appKey")} hint={t("approvalTemplates.test.appKeyHint")} error={errors.appKey}>
            <TextInput
              value={appKey}
              autoComplete="off"
              onChange={(event) => {
                setAppKey(event.currentTarget.value);
                if (event.currentTarget.value.trim() !== "") {
                  clearError("appKey");
                }
              }}
            />
          </Field>
        ) : null}
        <Field label={t("approvalTemplates.test.form")} error={errors.form}>
          <TextArea
            rows={5}
            spellCheck={false}
            className="font-mono text-caption"
            value={formText}
            onChange={(event) => {
              setFormText(event.currentTarget.value);
              clearError("form");
            }}
          />
        </Field>
        {testMutation.error ? (
          <StatusBanner live="alert" tone="signal" title={t("approvalTemplates.test.failed")} message={(testMutation.error as Error).message} />
        ) : null}
        {result ? <TemplateTestResult result={result} /> : null}
      </form>
    </Dialog>
  );
}

function TemplateTestResult({ result }: { result: ApprovalTemplateTestResult }) {
  const { t } = useI18n();
  return (
    <div className="space-y-3">
      <StatusBanner live="status" tone="evergreen" title={t("approvalTemplates.test.success")} />
      <dl className="grid gap-2 rounded-[3px] border border-ink/10 bg-paper-soft p-4 text-body text-ink-soft">
        <div className="flex items-center justify-between gap-4">
          <dt>{t("approvalTemplates.test.instanceId")}</dt>
          <dd className="font-mono text-ink">{result.instance_id}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt>{t("approvalTemplates.test.dingtalkInstanceId")}</dt>
          <dd className="font-mono text-ink">{result.dingtalk_process_instance_id || "-"}</dd>
        </div>
        <div className="flex items-center justify-between gap-4">
          <dt>{t("common.status")}</dt>
          <dd className="font-mono text-ink">{approvalStatusLabel(t, result.status)}</dd>
        </div>
      </dl>
    </div>
  );
}
