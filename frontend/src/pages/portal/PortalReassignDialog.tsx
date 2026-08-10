import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import type { HandoverTaskPayload, HandoverUserRef } from "../../lib/domain";

interface AppOption {
  app_key: string;
  app_name: string;
}

export function PortalReassignDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [subject, setSubject] = useState<HandoverUserRef | null>(null);
  const [selectedApps, setSelectedApps] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [formError, setFormError] = useState<string | null>(null);

  const appsQuery = useQuery({
    queryKey: ["portal", "handover-app-options", subject?.user_id],
    queryFn: () =>
      apiRequest<{ items: AppOption[] }>(
        `/portal/api/v1/handover-app-options?subject_user_id=${encodeURIComponent(subject!.user_id)}`,
      ),
    enabled: Boolean(subject?.user_id),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>("/portal/api/v1/handover-tasks/reassign", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: {
          subject_user_id: subject!.user_id,
          app_keys: selectedApps,
          reason: reason.trim(),
        },
      }),
    onSuccess: (payload) => {
      const id = payload.handover_task?.id;
      if (id) {
        void navigate(`/portal/handovers/${id}`);
      }
      onClose();
    },
  });

  const submit = () => {
    setFormError(null);
    if (!subject) {
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

  const outOfScope = Boolean(createMutation.error && apiErrorReason(createMutation.error) === "out_of_managed_scope");

  return (
    <Dialog
      title={t("handover.portal.reassign.title")}
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
          <ReassignSubjectPicker
            value={subject}
            onChange={(user) => {
              setSubject(user);
              setSelectedApps([]);
            }}
          />
        </Field>
        <Field label={t("handover.portal.reassign.apps")} hint={t("handover.portal.reassign.appsHint")} as="group">
          {!subject ? (
            <p className="text-body text-ink-faint">—</p>
          ) : appsQuery.isLoading ? (
            <p className="text-body text-ink-faint">{t("common.loading")}</p>
          ) : (
            <ul className="grid gap-1.5">
              {(appsQuery.data?.items ?? []).map((app) => {
                const checked = selectedApps.includes(app.app_key);
                return (
                  <li key={app.app_key}>
                    <label className="flex items-center gap-2 text-body text-ink">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={(event) => {
                          const nextChecked = event.currentTarget.checked;
                          setSelectedApps((current) =>
                            nextChecked
                              ? [...current, app.app_key]
                              : current.filter((key) => key !== app.app_key),
                          );
                        }}
                      />
                      <span>{app.app_name || app.app_key}</span>
                    </label>
                  </li>
                );
              })}
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
        {outOfScope ? (
          <StatusBanner live="alert" tone="signal" title={t("handover.portal.reassign.outOfScope")} />
        ) : null}
        {createMutation.error && !outOfScope ? (
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

/** 转出方专用：purpose=reassign_subject，与接收人候选隔离。 */
function ReassignSubjectPicker({
  value,
  onChange,
}: {
  value: HandoverUserRef | null;
  onChange: (user: HandoverUserRef | null) => void;
}) {
  const { t } = useI18n();
  const [input, setInput] = useState(value?.name ?? "");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setInput(value?.name ?? "");
  }, [value?.name, value?.user_id]);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(input.trim()), 300);
    return () => window.clearTimeout(id);
  }, [input]);

  const query = useQuery({
    queryKey: ["portal", "reassign-subject-candidates", debounced],
    queryFn: () =>
      apiRequest<{ items: Array<{ user_id: string; name: string; department?: string }> }>(
        `/portal/api/v1/handover-candidates?purpose=reassign_subject&q=${encodeURIComponent(debounced)}`,
      ),
    enabled: open,
    placeholderData: (previous) => previous,
  });

  return (
    <div className="relative">
      <TextInput
        aria-label={t("handover.portal.reassign.subject")}
        value={input}
        placeholder={t("handover.userPicker.placeholder")}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setInput(event.currentTarget.value);
          if (value) {
            onChange(null);
          }
          setOpen(true);
        }}
      />
      {open ? (
        <div className="absolute left-0 right-0 z-20 mt-1 max-h-48 overflow-auto rounded-[3px] border border-ink/12 bg-paper p-1 shadow-lg">
          {(query.data?.items ?? []).length === 0 ? (
            <p className="px-2 py-1.5 text-body text-ink-faint">{t("handover.userPicker.empty")}</p>
          ) : (
            (query.data?.items ?? []).map((item) => (
              <button
                key={item.user_id}
                type="button"
                className="block w-full px-2 py-1.5 text-left text-body hover:bg-paper-deep"
                onClick={() => {
                  onChange({ user_id: item.user_id, name: item.name, department: item.department });
                  setInput(item.name);
                  setOpen(false);
                }}
              >
                {item.name}
                {item.department ? <span className="ml-2 text-caption text-ink-faint">{item.department}</span> : null}
              </button>
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}
