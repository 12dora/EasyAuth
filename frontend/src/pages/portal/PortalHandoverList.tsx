import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageState } from "../../components/ui/PageState";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { daysLeftTone } from "../../features/handover/surface";
import { useI18n } from "../../i18n/I18nProvider";
import { apiRequest } from "../../lib/api";
import type { HandoverMeTasksPayload, HandoverTaskListItem } from "../../lib/domain";
import { PortalPreOffboardDialog } from "./PortalPreOffboardDialog";
import { PortalReassignDialog } from "./PortalReassignDialog";

export function PortalHandoverList() {
  const { t } = useI18n();
  const [preOpen, setPreOpen] = useState(false);
  const [reassignOpen, setReassignOpen] = useState(false);

  const listQuery = useQuery({
    queryKey: ["portal", "handover-tasks"],
    queryFn: () => apiRequest<HandoverMeTasksPayload>("/portal/api/v1/me/handover-tasks"),
  });

  const candidatesQuery = useQuery({
    queryKey: ["portal", "handover-candidates", "reassign_subject"],
    queryFn: () =>
      apiRequest<{ items: unknown[] }>("/portal/api/v1/handover-candidates?purpose=reassign_subject&q="),
  });

  const asAssignee = listQuery.data?.handover_tasks?.as_assignee ?? [];
  const asSubject = listQuery.data?.handover_tasks?.as_subject ?? [];
  const canReassign = (candidatesQuery.data?.items?.length ?? 0) > 0;

  if (listQuery.error && asAssignee.length === 0 && asSubject.length === 0) {
    return (
      <PageState
        tone="signal"
        title={t("handover.portal.list.loadFailed")}
        description={(listQuery.error as Error).message}
        action={
          <Button type="button" onClick={() => void listQuery.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={t("shell.portal.title")}
        title={t("handover.portal.list.title")}
        description={t("handover.portal.list.description")}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="ghost" onClick={() => setPreOpen(true)}>
              {t("handover.portal.list.preOffboard")}
            </Button>
            {canReassign ? (
              <Button type="button" variant="ghost" onClick={() => setReassignOpen(true)}>
                {t("handover.portal.list.reassign")}
              </Button>
            ) : null}
          </div>
        }
      />
      {listQuery.error ? (
        <StatusBanner
          live="alert"
          tone="signal"
          title={t("handover.portal.list.loadFailed")}
          message={(listQuery.error as Error).message}
        />
      ) : null}

      {asAssignee.length === 0 && asSubject.length === 0 && !listQuery.isLoading ? (
        <EmptyState title={t("handover.portal.list.empty")} />
      ) : (
        <div className="space-y-8">
          <section className="space-y-3" aria-labelledby="as-assignee-heading">
            <h2 id="as-assignee-heading" className="text-base font-semibold text-ink">
              {t("handover.portal.list.asAssignee")}
            </h2>
            {asAssignee.length === 0 ? (
              <p className="text-body text-ink-soft">{t("handover.portal.list.empty")}</p>
            ) : (
              <ul className="grid gap-3">
                {asAssignee.map((task) => (
                  <HandoverTaskCard key={task.id} task={task} interactive />
                ))}
              </ul>
            )}
          </section>
          <section className="space-y-3" aria-labelledby="as-subject-heading">
            <h2 id="as-subject-heading" className="text-base font-semibold text-ink">
              {t("handover.portal.list.asSubject")}
            </h2>
            {asSubject.length === 0 ? null : (
              <ul className="grid gap-3">
                {asSubject.map((task) => (
                  <HandoverTaskCard key={task.id} task={task} interactive={false} />
                ))}
              </ul>
            )}
          </section>
        </div>
      )}

      {preOpen ? <PortalPreOffboardDialog onClose={() => setPreOpen(false)} /> : null}
      {reassignOpen ? <PortalReassignDialog onClose={() => setReassignOpen(false)} /> : null}
    </>
  );
}

function HandoverTaskCard({ task, interactive }: { task: HandoverTaskListItem; interactive: boolean }) {
  const { t } = useI18n();
  const daysLeft = task.escalation?.days_left;
  const daysTone = daysLeftTone(daysLeft);
  const subjectName = task.subject.name || task.subject.user_id;
  const department = task.subject.department || "";

  return (
    <li>
      <PanelSurface padding="lg" className="space-y-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-body font-semibold text-ink">
              {subjectName}
              {department ? <span className="font-normal text-ink-soft"> · {department}</span> : null}
            </p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <Badge tone="bond">{kindLabel(t, task.kind)}</Badge>
              {task.escalation?.deadline == null ? (
                <Badge tone="neutral">{t("handover.portal.list.awaitingSuperuser")}</Badge>
              ) : (
                <span data-testid={`days-left-${task.id}`}>
                  <Badge tone={daysTone}>{t("handover.portal.list.daysLeft", { count: daysLeft ?? 0 })}</Badge>
                </span>
              )}
            </div>
          </div>
          <ButtonLink to={`/portal/handovers/${task.id}`} variant={interactive ? "primary" : "ghost"} size="sm">
            {t("handover.portal.list.handle")}
          </ButtonLink>
        </div>
        <p className="text-body text-ink-soft">
          {t("handover.portal.list.pendingApps", { count: task.pending_app_count })}
          {" · "}
          {t("handover.portal.list.totalAssets", { count: task.total_asset_count })}
        </p>
        {task.blocked_app_count > 0 ? (
          <p className="text-body text-signal" data-testid={`blocked-hint-${task.id}`}>
            ⚠ {t("handover.portal.list.blockedApps", { count: task.blocked_app_count })}
          </p>
        ) : null}
      </PanelSurface>
    </li>
  );
}

function kindLabel(t: ReturnType<typeof useI18n>["t"], kind: string): string {
  switch (kind) {
    case "offboard":
      return t("handover.kind.offboard");
    case "transfer":
      return t("handover.kind.transfer");
    case "pre_offboard":
      return t("handover.kind.pre_offboard");
    case "reassign":
      return t("handover.kind.reassign");
    default:
      return kind;
  }
}
