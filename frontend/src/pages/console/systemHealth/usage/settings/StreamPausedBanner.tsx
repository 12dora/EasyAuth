import { PlayCircle, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../../components/Button";
import { ConfirmDialog } from "../../../../../components/ui/ConfirmDialog";
import { useI18n } from "../../../../../i18n/I18nProvider";
import { useUsageSummary } from "../useUsageData";
import { useResumeStream } from "./useUsageSettings";

/** Stream 因超限被暂停时的横幅; 未暂停时不渲染任何内容。 */
export function StreamPausedBanner() {
  const { t, formatDateTime } = useI18n();
  const summary = useUsageSummary();
  const resumeMutation = useResumeStream();
  const [confirming, setConfirming] = useState(false);
  const stream = summary.data?.stream;

  if (!stream?.paused) {
    return null;
  }

  return (
    <>
      <div
        role="alert"
        className="flex flex-wrap items-start gap-3 rounded-[3px] border border-amber/30 bg-amber/8 px-4 py-3 text-amber"
      >
        <TriangleAlert size={18} aria-hidden="true" className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <strong className="block text-sm font-semibold leading-5">{t("usageStream.paused.title")}</strong>
          <p className="mt-1 text-sm leading-5 text-ink-soft">
            {stream.paused_at
              ? t("usageStream.paused.message", { since: formatDateTime(stream.paused_at) })
              : t("usageStream.paused.messageNoTime")}
          </p>
          {stream.can_resume ? null : (
            <p className="mt-1 text-xs leading-5 text-ink-faint">{t("usageStream.resume.blocked")}</p>
          )}
          {resumeMutation.error ? (
            <p className="mt-1 text-sm leading-5 text-signal">
              <span className="font-medium">{t("usageStream.resume.failed")}</span>
              <span className="ml-1 text-ink-soft">{resumeMutation.error.message}</span>
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          variant="primary"
          size="sm"
          icon={<PlayCircle size={14} />}
          disabled={!stream.can_resume}
          loading={resumeMutation.isPending}
          onClick={() => setConfirming(true)}
        >
          {t("usageStream.resume")}
        </Button>
      </div>
      {confirming ? (
        <ConfirmDialog
          title={t("usageStream.resume.confirmTitle")}
          message={t("usageStream.resume.confirmMessage")}
          confirmLabel={t("usageStream.resume.confirmAction")}
          danger={false}
          onConfirm={() => {
            setConfirming(false);
            resumeMutation.mutate();
          }}
          onClose={() => setConfirming(false)}
        />
      ) : null}
    </>
  );
}
