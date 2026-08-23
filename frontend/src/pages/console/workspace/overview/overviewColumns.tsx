import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "../../../../components/Badge";
import { TableActionCell, TableRowActionButton } from "../../../../components/ui/TableActions";
import type { ConfigurationIssue } from "../../../../lib/domain";
import type { Translator } from "../../../../lib/status";
import { roleLabel, type MembershipItem } from "./overviewModel";

export function membershipTableColumns({
  t,
  canWrite,
  onDisable,
}: {
  t: Translator;
  canWrite: boolean;
  onDisable: (membershipId: number) => void;
}): ColumnDef<MembershipItem>[] {
  return [
    { header: t("common.user"), cell: ({ row }) => <code>{row.original.user_id}</code> },
    { header: t("common.role"), cell: ({ row }) => roleLabel(t, row.original.role) },
    {
      header: t("common.status"),
      cell: ({ row }) => (
        <Badge tone={row.original.is_active ? "evergreen" : "neutral"}>
          {row.original.is_active ? t("common.enabled") : t("common.disabled")}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: t("common.actions"),
      cell: ({ row }) => (
        <TableActionCell>
          {canWrite && row.original.is_active ? (
            <TableRowActionButton type="button" variant="ghost-danger" onClick={() => onDisable(row.original.id)}>
              {t("common.disable")}
            </TableRowActionButton>
          ) : null}
        </TableActionCell>
      ),
    },
  ];
}

export function configurationIssueColumns(t: Translator): ColumnDef<ConfigurationIssue>[] {
  return [
    { header: t("console.overview.issue.severity"), cell: ({ row }) => row.original.severity ?? row.original.level ?? "-" },
    { header: t("console.overview.issue.subject"), cell: ({ row }) => row.original.subject ?? row.original.target_id ?? "-" },
    { header: t("console.overview.issue.message"), cell: ({ row }) => row.original.message ?? "-" },
    { header: t("console.overview.issue.code"), cell: ({ row }) => <code>{row.original.code ?? "-"}</code> },
  ];
}
