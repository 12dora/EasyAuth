import { ArrowRight } from "lucide-react";
import type { NavigateFunction } from "react-router-dom";

import type { ColumnsType, ServerSortState } from "../../components/antd/AppTable";
import {
  RowActionButton,
  RowActionLink,
  actionsColumn,
  activeStatusColumn,
  dateTimeColumn,
  serverSortColumn,
  textColumn,
} from "../../components/antd/columns";
import { userOptionName } from "../../components/UserCombobox";
import { joinLabels } from "../../lib/joinLabels";
import type { TeamSummary } from "../../lib/domain";
import type { Translator } from "../../lib/status";

export function teamLeadersLabel(leaders: TeamSummary["leaders"] | undefined): string {
  return joinLabels((leaders ?? []).map((leader) => userOptionName(leader)));
}

export function buildTeamColumns({
  navigate,
  sort,
  t,
  onDelete,
}: {
  navigate: NavigateFunction;
  sort: ServerSortState;
  t: Translator;
  onDelete: (team: TeamSummary) => void;
}): ColumnsType<TeamSummary> {
  return [
    serverSortColumn(
      {
        key: "name",
        dataIndex: "name",
        title: t("console.teams.column.name"),
        ellipsis: true,
        render: (_value: unknown, team: TeamSummary) => <strong>{team.name}</strong>,
      },
      sort,
    ),
    serverSortColumn(
      textColumn<TeamSummary>({
        key: "leaders",
        title: t("console.teams.column.leaders"),
        getValue: (team) => teamLeadersLabel(team.leaders),
        width: 220,
      }),
      sort,
    ),
    serverSortColumn(
      textColumn<TeamSummary>({
        key: "member_count",
        title: t("console.teams.column.memberCount"),
        getValue: (team) => String(team.member_count ?? 0),
        width: 110,
      }),
      sort,
    ),
    serverSortColumn(
      activeStatusColumn<TeamSummary>({
        t,
        getActive: (team) => team.is_active,
        filter: false,
        width: 110,
      }),
      sort,
    ),
    serverSortColumn(
      dateTimeColumn<TeamSummary>({
        key: "created_at",
        title: t("console.teams.column.createdAt"),
        sorter: false,
      }),
      sort,
    ),
    actionsColumn<TeamSummary>({
      render: (team) => (
        <>
          <RowActionLink
            href={`/console/teams/${team.id}`}
            icon={<ArrowRight size={15} />}
            onClick={(event) => {
              event.preventDefault();
              void navigate(`/console/teams/${team.id}`);
            }}
          >
            {t("console.teams.view")}
          </RowActionLink>
          <RowActionButton type="button" variant="ghost-danger" onClick={() => onDelete(team)}>
            {t("common.delete")}
          </RowActionButton>
        </>
      ),
    }),
  ];
}
