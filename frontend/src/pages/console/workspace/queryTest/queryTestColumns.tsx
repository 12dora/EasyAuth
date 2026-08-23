import type { ColumnDef } from "@tanstack/react-table";

import type { Translator } from "../../../../lib/status";
import type { QueryTestGrant, QueryTestGroup } from "./queryTestModel";

export function queryTestGroupColumns(t: Translator, resultSnapshotVersion: string | undefined): ColumnDef<QueryTestGroup>[] {
  return [
    { header: t("console.queryTest.column.group"), cell: ({ row }) => row.original.key ?? "-" },
    { header: t("common.name"), cell: ({ row }) => row.original.name ?? "-" },
    { header: t("common.source"), cell: ({ row }) => row.original.source ?? "-" },
    { header: t("wizard.verify.snapshotVersion"), cell: ({ row }) => row.original.snapshot_version ?? resultSnapshotVersion ?? "-" },
  ];
}

export function queryTestGrantColumns(t: Translator, resultSnapshotVersion: string | undefined): ColumnDef<QueryTestGrant>[] {
  return [
    { header: t("console.queryTest.column.grant"), cell: ({ row }) => row.original.permission ?? "-" },
    { header: t("console.queryTest.column.scope"), cell: ({ row }) => row.original.scope ?? "-" },
    { header: t("common.name"), cell: ({ row }) => row.original.name ?? "-" },
    { header: t("common.type"), cell: ({ row }) => row.original.grant_type ?? "-" },
    {
      header: t("common.source"),
      cell: ({ row }) => (row.original.source_key ? `${row.original.source_type ?? "-"}:${row.original.source_key}` : row.original.source_type ?? "-"),
    },
    { header: t("console.queryTest.column.resolvedUsers"), cell: ({ row }) => (row.original.resolved ? row.original.resolved.user_ids.length : "-") },
    { header: "Resolver", cell: ({ row }) => row.original.resolved?.resolver ?? "-" },
    { header: "Resolved at", cell: ({ row }) => row.original.resolved?.resolved_at ?? "-" },
    { header: t("wizard.verify.snapshotVersion"), cell: ({ row }) => row.original.snapshot_version ?? resultSnapshotVersion ?? "-" },
  ];
}
