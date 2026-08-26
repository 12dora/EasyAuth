import { RowActionButton, actionsColumn, textColumn } from "../../../../components/antd/columns";
import { enumFilter, type ColumnsType } from "../../../../components/antd/AppTable";
import type { ConfigurationIssue } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { activeStatusColumn } from "../workspaceColumns";
import { roleLabel, type MembershipItem } from "./overviewModel";

export function membershipTableColumns({
  t,
  canWrite,
  onDisable,
}: {
  t: Translator;
  canWrite: boolean;
  onDisable: (membershipId: number) => void;
}): ColumnsType<MembershipItem> {
  return [
    textColumn<MembershipItem>({ key: "user_id", title: t("common.user"), mono: true, filter: true }),
    {
      key: "role",
      dataIndex: "role",
      title: t("common.role"),
      width: 140,
      render: (_value: unknown, membership: MembershipItem) => roleLabel(t, membership.role),
      ...enumFilter<MembershipItem>("role", [
        { label: t("console.overview.role.owner"), value: "owner" },
        { label: t("console.overview.role.developer"), value: "developer" },
      ]),
    },
    activeStatusColumn<MembershipItem>({ t, getActive: (membership) => membership.is_active }),
    actionsColumn<MembershipItem>({
      title: t("common.actions"),
      render: (membership) =>
        canWrite && membership.is_active ? (
          <RowActionButton type="button" variant="ghost-danger" onClick={() => onDisable(membership.id)}>
            {t("common.disable")}
          </RowActionButton>
        ) : null,
    }),
  ];
}

export function configurationIssueColumns(t: Translator): ColumnsType<ConfigurationIssue> {
  return [
    textColumn<ConfigurationIssue>({
      key: "severity",
      title: t("console.overview.issue.severity"),
      getValue: (issue) => issue.severity ?? issue.level,
      filter: true,
      sorter: true,
      width: 120,
    }),
    textColumn<ConfigurationIssue>({
      key: "subject",
      title: t("console.overview.issue.subject"),
      getValue: (issue) => issue.subject ?? issue.target_id,
      filter: true,
      width: 220,
    }),
    textColumn<ConfigurationIssue>({ key: "message", title: t("console.overview.issue.message") }),
    textColumn<ConfigurationIssue>({
      key: "code",
      title: t("console.overview.issue.code"),
      mono: true,
      filter: true,
      width: 200,
    }),
  ];
}
