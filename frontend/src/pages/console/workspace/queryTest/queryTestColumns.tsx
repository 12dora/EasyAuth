import type { ColumnsType } from "../../../../components/antd/AppTable";
import { textColumn } from "../../../../components/antd/columns";
import type { Translator } from "../../../../lib/status";
import type { QueryTestGrant, QueryTestGroup } from "./queryTestModel";

export function queryTestGroupColumns(
  t: Translator,
  resultSnapshotVersion: string | undefined,
): ColumnsType<QueryTestGroup> {
  return [
    textColumn<QueryTestGroup>({
      key: "key",
      title: t("console.queryTest.column.group"),
      mono: true,
      filter: true,
      sorter: true,
    }),
    textColumn<QueryTestGroup>({ key: "name", title: t("common.name"), filter: true, sorter: true }),
    textColumn<QueryTestGroup>({ key: "source", title: t("common.source"), width: 160 }),
    textColumn<QueryTestGroup>({
      key: "snapshot_version",
      title: t("wizard.verify.snapshotVersion"),
      getValue: (group) => group.snapshot_version ?? resultSnapshotVersion,
      mono: true,
      width: 200,
    }),
  ];
}

export function queryTestGrantColumns(
  t: Translator,
  resultSnapshotVersion: string | undefined,
): ColumnsType<QueryTestGrant> {
  return [
    textColumn<QueryTestGrant>({
      key: "permission",
      title: t("console.queryTest.column.grant"),
      mono: true,
      filter: true,
      sorter: true,
    }),
    textColumn<QueryTestGrant>({ key: "scope", title: t("console.queryTest.column.scope"), width: 140 }),
    textColumn<QueryTestGrant>({ key: "name", title: t("common.name"), filter: true }),
    textColumn<QueryTestGrant>({ key: "grant_type", title: t("common.type"), width: 120 }),
    textColumn<QueryTestGrant>({
      key: "source",
      title: t("common.source"),
      getValue: (grant) =>
        grant.source_key ? `${grant.source_type ?? "-"}:${grant.source_key}` : grant.source_type,
      mono: true,
      width: 200,
    }),
    textColumn<QueryTestGrant>({
      key: "resolved_users",
      title: t("console.queryTest.column.resolvedUsers"),
      getValue: (grant) => (grant.resolved ? String(grant.resolved.user_ids.length) : undefined),
      width: 140,
    }),
    textColumn<QueryTestGrant>({
      key: "resolver",
      title: "Resolver",
      getValue: (grant) => grant.resolved?.resolver,
      width: 140,
    }),
    textColumn<QueryTestGrant>({
      key: "resolved_at",
      title: "Resolved at",
      getValue: (grant) => grant.resolved?.resolved_at,
      width: 200,
    }),
    textColumn<QueryTestGrant>({
      key: "snapshot_version",
      title: t("wizard.verify.snapshotVersion"),
      getValue: (grant) => grant.snapshot_version ?? resultSnapshotVersion,
      mono: true,
      width: 200,
    }),
  ];
}
