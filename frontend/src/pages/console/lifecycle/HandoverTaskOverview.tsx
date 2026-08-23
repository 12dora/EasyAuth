import type { ReactNode } from "react";

import { Badge } from "../../../components/Badge";
import { Button } from "../../../components/Button";
import { PanelSurface } from "../../../components/ui/PanelSurface";
import { daysLeftTone } from "../../../features/handover/surface";
import { useI18n } from "../../../i18n/I18nProvider";
import type { HandoverTaskDetail } from "../../../lib/domain";
import { formatDateTime } from "../../../lib/status";
import {
  handoverAssigneeStateLabel,
  handoverKindLabel,
  handoverTaskStatusLabel,
  handoverTaskStatusTone,
  personStatusLabel,
  personStatusTone,
} from "./lifecycleLabels";

export function OverviewItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

export function SubjectPanel({ task, subjectName }: { task: HandoverTaskDetail; subjectName: string }) {
  const { t } = useI18n();
  const subjectStatus = task.subject.status ?? "";
  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("handover.detail.subject")}</h2>
        <Badge tone={handoverTaskStatusTone(task.status)}>{handoverTaskStatusLabel(t, task.status)}</Badge>
      </div>
      <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
        <OverviewItem
          label={t("handover.detail.subject")}
          value={
            <span className="inline-flex items-center gap-1.5">
              {subjectName}
              {subjectStatus ? (
                <Badge tone={personStatusTone(subjectStatus)}>{personStatusLabel(t, subjectStatus)}</Badge>
              ) : null}
            </span>
          }
        />
        <OverviewItem label={t("handover.list.column.kind")} value={handoverKindLabel(t, task.kind)} />
        <OverviewItem label={t("people.column.department")} value={task.subject.department || "-"} />
        <OverviewItem label={t("people.column.email")} value={task.subject.email || "-"} />
        <OverviewItem label={t("handover.detail.createdAt")} value={formatDateTime(task.created_at)} />
        <OverviewItem label={t("handover.detail.createdBy")} value={task.created_by || "-"} />
      </dl>
      {task.reason ? (
        <p className="max-w-3xl text-body leading-5 text-ink-soft">
          {t("handover.detail.reason")}: {task.reason}
        </p>
      ) : null}
    </PanelSurface>
  );
}

export interface AssigneePanelProps {
  task: HandoverTaskDetail;
  isLocalAdmin: boolean;
  claimPending: boolean;
  onDefer: () => void;
  onClaim: () => void;
}

export function AssigneePanel({ task, isLocalAdmin, claimPending, onDefer, onClaim }: AssigneePanelProps) {
  const { t } = useI18n();
  const canDefer = task.escalation.deferred_at == null && task.escalation.deadline != null;
  const canClaim = task.assignee_state === "superuser_pool";
  return (
    <PanelSurface padding="lg" className="space-y-3" data-testid="assignee-card">
      <h2 className="text-base font-semibold text-ink">{t("handover.console.assigneeCard")}</h2>
      <dl className="grid gap-2 text-body sm:grid-cols-2">
        <OverviewItem
          label={t("handover.console.assigneeCard")}
          value={task.assignee?.name || task.assignee?.user_id || "-"}
        />
        <OverviewItem
          label={t("handover.console.filter.assigneeState")}
          value={handoverAssigneeStateLabel(t, task.assignee_state)}
        />
        <OverviewItem label={t("handover.portal.detail.escalated")} value={String(task.escalation_level)} />
        <OverviewItem
          label={t("handover.console.escalationDeadline")}
          value={
            task.escalation.deadline
              ? `${formatDateTime(task.escalation.deadline)} · ${t("handover.console.daysLeft", { count: task.escalation.days_left ?? 0 })}`
              : t("handover.portal.list.awaitingSuperuser")
          }
        />
      </dl>
      {task.escalation.days_left != null ? (
        <Badge tone={daysLeftTone(task.escalation.days_left)}>
          {t("handover.console.daysLeft", { count: task.escalation.days_left })}
        </Badge>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={!canDefer} onClick={onDefer} data-testid="defer-button">
          {t("handover.console.defer")}
        </Button>
        {canClaim ? (
          <Button
            type="button"
            size="sm"
            variant="primary"
            disabled={isLocalAdmin}
            title={isLocalAdmin ? t("handover.console.claimDisabledLocalAdmin") : undefined}
            loading={claimPending}
            onClick={onClaim}
            data-testid="claim-button"
          >
            {t("handover.console.claim")}
          </Button>
        ) : null}
      </div>
      {(task.escalation.defer_history?.length ?? 0) > 0 ? (
        <div className="space-y-1">
          <h3 className="text-caption font-semibold text-ink-soft">{t("handover.console.deferHistory")}</h3>
          <ul className="grid gap-1 text-caption text-ink-faint">
            {task.escalation.defer_history.map((entry, index) => (
              <li key={`${entry.at}-${index}`}>
                L{entry.escalation_level} · {entry.actor_id} · {formatDateTime(entry.at)} · {entry.reason}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </PanelSurface>
  );
}
