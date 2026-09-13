import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, TextArea, TextInput } from "../../components/Field";
import { StatusBanner } from "../../components/StatusBanner";
import { UserOptionList, useUserCombobox } from "../../components/UserCombobox";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import { formatAppDisplayName } from "../../lib/appDisplayName";
import { apiErrorReason } from "../../lib/apiErrorReason";
import type { HandoverCandidate, HandoverTaskPayload, HandoverUserRef } from "../../lib/domain";

interface AppOption {
  app_key: string;
  app_name: string;
  app_alias: string;
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

  const mutationErrorTitle = resolveReassignErrorTitle(createMutation.error, t);

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
                      <span>{formatAppDisplayName({ name: app.app_name, alias: app.app_alias })}</span>
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
        {mutationErrorTitle ? <StatusBanner live="alert" tone="signal" title={mutationErrorTitle} /> : null}
      </div>
    </Dialog>
  );
}

function resolveReassignErrorTitle(
  error: unknown,
  t: ReturnType<typeof useI18n>["t"],
): string | null {
  if (!error) {
    return null;
  }
  const reason = apiErrorReason(error);
  switch (reason) {
    case "out_of_managed_scope":
      return t("handover.portal.reassign.outOfScope");
    case "directory_unavailable":
      return t("handover.portal.reassign.directoryUnavailable");
    case "handover_execution_in_flight":
      return t("handover.portal.reassign.executionInFlight");
    case "action_blocked":
      return t("handover.portal.reassign.actionBlocked");
    case "idempotency_conflict":
      return t("handover.portal.reassign.idempotencyConflict");
    default:
      return t("handover.portal.reassign.failed");
  }
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
  const generatedId = useId();
  const listId = `${generatedId}-listbox`;
  const [input, setInput] = useState(value?.name ?? "");

  useEffect(() => {
    setInput(value?.name ?? "");
  }, [value?.name, value?.user_id]);

  const { open, setOpen, options, optionsQuery, highlightIndex, activeOption, containerRef, onKeyDown, pick } =
    useUserCombobox({
      query: input.trim(),
      optionSource: {
        queryKey: ["portal", "reassign-subject-candidates"],
        queryFn: async (debouncedQuery) => {
          const payload = await apiRequest<{ items: HandoverCandidate[] }>(
            `/portal/api/v1/handover-candidates?purpose=reassign_subject&q=${encodeURIComponent(debouncedQuery)}`,
          );
          return payload.items ?? [];
        },
        allowEmptyQuery: true,
      },
      debounceMs: 300,
      navigateWhenClosed: false,
      openOnArrowDown: false,
      closeOnPick: true,
      onPick: (option) => {
        onChange({ user_id: option.user_id, name: option.name, department: option.department });
        setInput(option.name);
      },
    });

  const getOptionId = (option: { user_id: string }) => `${listId}-option-${encodeURIComponent(option.user_id)}`;

  return (
    <div className="relative" ref={containerRef}>
      <TextInput
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-activedescendant={activeOption ? getOptionId(activeOption) : undefined}
        autoComplete="off"
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
        onKeyDown={onKeyDown}
      />
      {open ? (
        <UserOptionList
          listId={listId}
          options={options}
          isLoading={optionsQuery.isLoading || optionsQuery.isFetching}
          error={optionsQuery.error as Error | null}
          highlightIndex={highlightIndex}
          getOptionId={getOptionId}
          onPick={pick}
          onRetry={() => void optionsQuery.refetch()}
          emptyLabel={t("handover.userPicker.empty")}
          loadingLabel={t("handover.userPicker.loading")}
        />
      ) : null}
    </div>
  );
}
