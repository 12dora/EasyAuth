import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { Dialog } from "../../components/Dialog";
import { StatusBanner } from "../../components/StatusBanner";
import { useI18n } from "../../i18n/I18nProvider";
import { ApiError, apiRequest } from "../../lib/api";
import { apiErrorReason } from "../../lib/apiErrorReason";
import type { HandoverTaskPayload } from "../../lib/domain";

export function PortalPreOffboardDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [idempotencyKey] = useState(() => crypto.randomUUID());
  const [existingTaskId, setExistingTaskId] = useState<number | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      apiRequest<HandoverTaskPayload>("/portal/api/v1/handover-tasks/pre-offboard", {
        method: "POST",
        body: {},
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    onSuccess: (payload) => {
      const id = payload.handover_task?.id;
      if (id) {
        void navigate(`/portal/handovers/${id}`);
      }
      onClose();
    },
    onError: (error: Error) => {
      if (apiErrorReason(error) === "open_task_exists") {
        const details = error instanceof ApiError ? error.details : undefined;
        const taskId =
          details && typeof details === "object" && !Array.isArray(details)
            ? (details as { task_id?: unknown }).task_id
            : undefined;
        setExistingTaskId(typeof taskId === "number" ? taskId : -1);
      }
    },
  });

  const noticeId = useId();

  return (
    <Dialog
      title={t("handover.portal.preOffboard.title")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button type="button" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            type="button"
            variant="primary"
            loading={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {t("handover.portal.preOffboard.confirm")}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <p id={noticeId} className="text-body leading-5 text-ink-soft">
          {t("handover.portal.preOffboard.notice")}
        </p>
        {existingTaskId !== null ? (
          <div className="space-y-2">
            <StatusBanner live="alert" tone="amber" title={t("handover.portal.preOffboard.openExists")} />
            {existingTaskId > 0 ? (
              <ButtonLink to={`/portal/handovers/${existingTaskId}`}>{t("handover.portal.preOffboard.goExisting")}</ButtonLink>
            ) : null}
          </div>
        ) : null}
        {createMutation.error && existingTaskId === null ? (
          <StatusBanner
            live="alert"
            tone="signal"
            title={t("handover.portal.preOffboard.failed")}
            message={(createMutation.error as Error).message}
          />
        ) : null}
      </div>
    </Dialog>
  );
}
