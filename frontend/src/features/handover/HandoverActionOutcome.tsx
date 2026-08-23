import { Button } from "../../components/Button";
import { useI18n } from "../../i18n/I18nProvider";
import type { HandoverAction } from "../../lib/domain";

/** done 段: 逐资产类型的处理计数; 无 summary 时给出空态文案。 */
export function HandoverActionDoneSummary({ action }: { action: HandoverAction }) {
  const { t } = useI18n();
  if (!action.summary || Object.keys(action.summary).length === 0) {
    return (
      <p className="text-body text-ink-soft" data-testid="done-summary-empty">
        {t("handover.portal.detail.summaryEmpty")}
      </p>
    );
  }
  return (
    <ul className="grid gap-1 text-body text-ink-soft" data-testid="done-summary">
      {Object.entries(action.summary).map(([type, summary]) => (
        <li key={type} data-testid={`done-summary-${type}`}>
          <strong className="text-ink">{type}</strong>:{" "}
          {t("handover.portal.detail.summaryTransferred", { count: summary.transferred })}
          {" · "}
          {t("handover.portal.detail.summaryReleased", { count: summary.released })}
          {" · "}
          {t("handover.portal.detail.summarySkipped", { count: summary.skipped })}
          {" · "}
          {t("handover.portal.detail.summaryMerged", { count: summary.merged })}
          {" · "}
          {t("handover.portal.detail.summaryFailed", { count: summary.failed })}
        </li>
      ))}
    </ul>
  );
}

export interface HandoverActionFailedSectionProps {
  action: HandoverAction;
  isConsoleSuperuser: boolean;
  showRawErrorButton: boolean;
  rawError: string | null;
  retryPending: boolean;
  onRetry: () => void;
  onSkip: () => void;
  onLoadRawError: () => void;
}

/** failed 段: 区分数据阶段/授权阶段失败, 提供重试、跳过与原始错误。 */
export function HandoverActionFailedSection({
  action,
  isConsoleSuperuser,
  showRawErrorButton,
  rawError,
  retryPending,
  onRetry,
  onSkip,
  onLoadRawError,
}: HandoverActionFailedSectionProps) {
  const { t } = useI18n();
  return (
    <div className="space-y-2">
      <p className="text-body font-medium text-ink">
        {action.data_completed_at
          ? t("handover.portal.detail.failedGrantPending")
          : t("handover.portal.detail.failedDataPending")}
      </p>
      {action.last_error ? <p className="text-caption text-signal">{action.last_error}</p> : null}
      <div className="flex flex-wrap gap-2">
        {action.allowed_actions.includes("retry") ? (
          <Button type="button" size="sm" loading={retryPending} onClick={onRetry}>
            {t("handover.portal.detail.retry")}
          </Button>
        ) : null}
        {action.allowed_actions.includes("skip") && isConsoleSuperuser ? (
          <Button type="button" size="sm" variant="ghost-danger" onClick={onSkip}>
            {t("handover.console.skip")}
          </Button>
        ) : null}
        {!action.allowed_actions.includes("retry") && !action.allowed_actions.includes("skip") ? (
          <p className="text-body text-ink-soft">{t("handover.portal.detail.notRetryable")}</p>
        ) : null}
        {showRawErrorButton ? (
          <Button type="button" size="sm" variant="ghost" onClick={onLoadRawError}>
            {t("handover.console.viewRawError")}
          </Button>
        ) : null}
      </div>
      {rawError ? <pre className="max-h-40 overflow-auto text-caption text-ink-faint">{rawError}</pre> : null}
    </div>
  );
}

export interface HandoverActionOutcomeSectionProps extends HandoverActionFailedSectionProps {
  status: HandoverAction["status"];
}

/** 终态展示: done 走处理汇总, failed 走失败与补救入口。 */
export function HandoverActionOutcomeSection({ status, ...props }: HandoverActionOutcomeSectionProps) {
  if (status === "done") {
    return <HandoverActionDoneSummary action={props.action} />;
  }
  if (status === "failed") {
    return <HandoverActionFailedSection {...props} />;
  }
  return null;
}
