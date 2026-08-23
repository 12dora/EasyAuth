import type { ReactNode } from "react";

import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useI18n } from "../../i18n/I18nProvider";
import { formatDateTime } from "../../lib/status";
import { teamLeadersLabel } from "./ConsoleTeamList";
import type { TeamInfoView } from "./consoleTeamDetailModel";

export interface TeamInfoPanelActions {
  savePending: boolean;
  statusPending: boolean;
  onEdit: () => void;
  onDisable: () => void;
  onEnable: () => void;
}

export function ConsoleTeamInfoPanel({ view, actions }: { view: TeamInfoView; actions: TeamInfoPanelActions }) {
  const { t } = useI18n();

  return (
    <PanelSurface padding="lg" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">{t("console.teams.info")}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" disabled={!view.hasTeam || actions.savePending} onClick={actions.onEdit}>
            {t("common.edit")}
          </Button>
          {view.isActive ? (
            <Button type="button" variant="ghost-danger" disabled={actions.statusPending} onClick={actions.onDisable}>
              {t("common.disable")}
            </Button>
          ) : (
            <Button
              type="button"
              disabled={!view.hasTeam || actions.statusPending}
              loading={actions.statusPending}
              onClick={actions.onEnable}
            >
              {t("common.enable")}
            </Button>
          )}
        </div>
      </div>
      <dl className="grid gap-x-8 gap-y-3 text-body sm:grid-cols-2">
        <TeamInfoItem label={t("console.teams.column.name")} value={view.name} />
        <TeamInfoItem
          label={t("common.status")}
          value={
            <Badge tone={view.isActive ? "evergreen" : "neutral"}>
              {view.isActive ? t("common.enabled") : t("common.disabled")}
            </Badge>
          }
        />
        <TeamInfoItem label={t("console.teams.column.leaders")} value={teamLeadersLabel(view.leaders)} />
        <TeamInfoItem label={t("console.teams.column.memberCount")} value={view.memberCount} />
        <TeamInfoItem label={t("console.teams.column.createdAt")} value={formatDateTime(view.createdAt)} />
        <TeamInfoItem label={t("common.updatedAt")} value={formatDateTime(view.updatedAt)} />
      </dl>
      {view.description ? <p className="max-w-3xl text-body leading-5 text-ink-soft">{view.description}</p> : null}
    </PanelSurface>
  );
}

function TeamInfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-ink/8 pb-2">
      <dt className="shrink-0 text-caption text-ink-faint">{label}</dt>
      <dd className="m-0 min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}
