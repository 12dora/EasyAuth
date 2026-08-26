import { useMemo } from "react";

import { AppTable, type ColumnsType } from "../../components/antd/AppTable";
import { actionsColumn, dateTimeColumn, statusColumn, textColumn, userColumn } from "../../components/antd/columns";
import { Button } from "../../components/Button";
import { useI18n } from "../../i18n/I18nProvider";
import type { TeamMemberItem } from "../../lib/domain";
import type { Translator } from "../../lib/status";
import { teamMemberRoleLabel } from "./consoleTeamDetailModel";

export interface TeamMemberTableActions {
  disabled: boolean;
  onToggleRole: (member: TeamMemberItem) => void;
  onRemove: (member: TeamMemberItem) => void;
}

export function ConsoleTeamMemberTable({
  members,
  isLoading,
  actions,
}: {
  members: TeamMemberItem[];
  isLoading: boolean;
  actions: TeamMemberTableActions;
}) {
  const { t } = useI18n();
  const columns = useMemo(() => teamMemberTableColumns(t, actions), [actions, t]);

  return (
    // 成员由团队详情一次性返回, 因此分页/筛选/排序全部在客户端完成。
    <AppTable<TeamMemberItem>
      columns={columns}
      dataSource={members}
      emptyDescription={t("console.teams.membersEmptyDescription")}
      emptyTitle={t("console.teams.membersEmpty")}
      loading={isLoading}
      minWidth={880}
      rowKey="id"
    />
  );
}

function teamMemberTableColumns(t: Translator, actions: TeamMemberTableActions): ColumnsType<TeamMemberItem> {
  return [
    userColumn<TeamMemberItem>({
      key: "member",
      title: t("console.teams.column.member"),
      getName: (member) => member.name || member.user_id,
      getUserId: (member) => member.user_id,
      filter: true,
    }),
    textColumn<TeamMemberItem>({
      key: "department",
      title: t("console.teams.column.department"),
      filter: true,
      width: 180,
    }),
    statusColumn<TeamMemberItem>({
      key: "role",
      title: t("common.role"),
      options: [
        { value: "leader", label: teamMemberRoleLabel(t, "leader"), tone: "bond" },
        { value: "member", label: teamMemberRoleLabel(t, "member"), tone: "neutral" },
      ],
      width: 140,
    }),
    dateTimeColumn<TeamMemberItem>({ key: "added_at", title: t("console.teams.column.addedAt") }),
    actionsColumn<TeamMemberItem>({
      render: (member) => (
        <>
          <Button type="button" size="sm" variant="ghost" disabled={actions.disabled} onClick={() => actions.onToggleRole(member)}>
            {member.role === "leader" ? t("console.teams.setMember") : t("console.teams.setLeader")}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost-danger"
            disabled={actions.disabled}
            onClick={() => actions.onRemove(member)}
          >
            {t("common.remove")}
          </Button>
        </>
      ),
    }),
  ];
}
