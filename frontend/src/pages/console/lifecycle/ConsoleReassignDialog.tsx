import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../../components/Button";
import { Dialog } from "../../../components/Dialog";
import { Field, TextArea } from "../../../components/Field";
import { StatusBanner } from "../../../components/StatusBanner";
import { UserSearchInput } from "../../../components/UserSelect";
import { useI18n } from "../../../i18n/I18nProvider";
import { apiRequest } from "../../../lib/api";
import { formatAppDisplayName } from "../../../lib/appDisplayName";
import type { HandoverTaskPayload } from "../../../lib/domain";

interface AppOption {
  app_key: string;
  app_name: string;
  app_alias: string;
}

/** 控制台超管跨管辖范围在职数据移交（D9）。 */
export function ConsoleReassignDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [subjectUserId, setSubjectUserId] = useState("");
  const [selectedApps, setSelectedApps] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [idempotencyKey] = useState(() => crypto.randomUUID());

  const appsQuery = useQuery({
    queryKey: ["console", "handover-app-options", subjectUserId],
    queryFn: () =>
      apiRequest<{ items: AppOption[] }>(
        `/console/api/v1/lifecycle/handover-app-options?subject_user_id=${encodeURIComponent(subjectUserId)}`,
      ),
    enabled: Boolean(subjectUserId.trim()),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>("/console/api/v1/lifecycle/handover-tasks/reassign", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: {
          subject_user_id: subjectUserId.trim(),
          app_keys: selectedApps,
          reason: reason.trim(),
        },
      }),
    onSuccess: (payload) => {
      const id = payload.handover_task?.id;
      if (id) {
        void navigate(`/console/lifecycle/handover-tasks/${id}`);
      }
      onClose();
    },
  });

  const submit = () => {
    setFormError(null);
    if (!subjectUserId.trim()) {
      setFormError(t("handover.portal.reassign.subject"));
      return;
    }
    if (selectedApps.length === 0) {
      setFormError(t("handover.portal.reassign.appsRequired"));
      return;
    }
    if (reason.trim().length < 10) {
      setFormError(t("handover.portal.reassign.reasonRequired"));
      return;
    }
    createMutation.mutate();
  };

  return (
    <Dialog
      title={t("handover.console.reassignTitle")}
      size="md"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button type="button" variant="primary" loading={createMutation.isPending} onClick={submit}>
            {t("handover.portal.reassign.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label={t("handover.portal.reassign.subject")} as="group">
          <UserSearchInput
            value={subjectUserId}
            aria-label={t("handover.portal.reassign.subject")}
            onChange={(value) => {
              setSubjectUserId(value);
              setSelectedApps([]);
            }}
          />
        </Field>
        <Field label={t("handover.portal.reassign.apps")} hint={t("handover.portal.reassign.appsHint")} as="group">
          {!subjectUserId.trim() ? (
            <p className="text-body text-ink-faint">—</p>
          ) : appsQuery.isLoading ? (
            <p className="text-body text-ink-faint">{t("common.loading")}</p>
          ) : (
            <ul className="grid gap-1.5">
              {(appsQuery.data?.items ?? []).map((app) => (
                <li key={app.app_key}>
                  <label className="flex items-center gap-2 text-body">
                    <input
                      type="checkbox"
                      checked={selectedApps.includes(app.app_key)}
                      onChange={(event) => {
                        setSelectedApps((current) =>
                          event.currentTarget.checked
                            ? [...current, app.app_key]
                            : current.filter((key) => key !== app.app_key),
                        );
                      }}
                    />
                    <span>{formatAppDisplayName({ name: app.app_name, alias: app.app_alias })}</span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </Field>
        <Field label={t("handover.portal.reassign.reason")} hint={t("handover.portal.reassign.reasonHint")}>
          <TextArea
            value={reason}
            aria-label={t("handover.portal.reassign.reason")}
            onChange={(event) => setReason(event.currentTarget.value)}
          />
        </Field>
        {formError ? <StatusBanner live="alert" tone="signal" title={formError} /> : null}
        {createMutation.error ? (
          <StatusBanner
            live="alert"
            tone="signal"
            title={t("handover.portal.reassign.failed")}
            message={(createMutation.error as Error).message}
          />
        ) : null}
      </div>
    </Dialog>
  );
}
