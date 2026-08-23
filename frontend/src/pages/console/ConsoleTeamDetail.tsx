import { Plus, RefreshCcw } from "lucide-react";

import { Button } from "../../components/Button";
import { ButtonLink } from "../../components/ButtonLink";
import { PageHeader } from "../../components/PageHeader";
import { StatusBanner } from "../../components/StatusBanner";
import { PageState } from "../../components/ui/PageState";
import { PanelSurface } from "../../components/ui/PanelSurface";
import { useI18n } from "../../i18n/I18nProvider";
import { ConsoleTeamDetailDialogs } from "./ConsoleTeamDetailDialogs";
import { ConsoleTeamInfoPanel } from "./ConsoleTeamInfoPanel";
import { ConsoleTeamMemberTable } from "./ConsoleTeamMemberTable";
import { teamInfoView } from "./consoleTeamDetailModel";
import { useConsoleTeamDetail } from "./useConsoleTeamDetail";

export function ConsoleTeamDetail() {
  const { t } = useI18n();
  const page = useConsoleTeamDetail();
  const { teamQuery, team, members } = page;
  const view = teamInfoView(team, members.length);

  if (teamQuery.error && !team) {
    return (
      <PageState
        tone="signal"
        title={t("console.teams.loadFailed")}
        description={(teamQuery.error as Error).message}
        action={
          <Button icon={<RefreshCcw size={16} />} loading={teamQuery.isFetching} onClick={() => void teamQuery.refetch()}>
            {t("common.retry")}
          </Button>
        }
      />
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={t("console.teams.eyebrow")}
        title={view.name}
        description={view.description || undefined}
        actions={<ButtonLink to="/console/teams">{t("console.teams.backToList")}</ButtonLink>}
      />
      {teamQuery.error && team ? (
        <StatusBanner live="alert" tone="signal" title={t("console.teams.loadFailed")} message={(teamQuery.error as Error).message} />
      ) : null}
      <section className="space-y-6">
        <ConsoleTeamInfoPanel
          view={view}
          actions={{
            savePending: page.saveInfoMutation.isPending,
            statusPending: page.statusMutation.isPending,
            onEdit: page.openEditDialog,
            onDisable: page.openDisableConfirm,
            onEnable: () => page.statusMutation.mutate(true),
          }}
        />
        <PanelSurface padding="lg" className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-base font-semibold text-ink">{t("console.teams.members")}</h2>
            <Button
              type="button"
              variant="primary"
              icon={<Plus size={16} />}
              disabled={!view.hasTeam}
              onClick={page.openAddMemberDialog}
            >
              {t("console.teams.addMember")}
            </Button>
          </div>
          <ConsoleTeamMemberTable
            members={members}
            isLoading={teamQuery.isLoading}
            actions={{
              disabled: page.changeRoleMutation.isPending || page.removeMemberMutation.isPending,
              onToggleRole: (member) =>
                page.changeRoleMutation.mutate({
                  memberId: member.id,
                  role: member.role === "leader" ? "member" : "leader",
                }),
              onRemove: page.setMemberPendingRemoval,
            }}
          />
        </PanelSurface>
      </section>
      <ConsoleTeamDetailDialogs page={page} team={team} />
    </>
  );
}
