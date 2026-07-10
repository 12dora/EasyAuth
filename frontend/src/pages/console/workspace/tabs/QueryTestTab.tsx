import { useMutation } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";
import { Play } from "lucide-react";
import { useState } from "react";
import { TableBody, TableCell, TableEmptyRow, TableFrame, TableHead, TableHeaderCell, TableRoot, TableRow } from "../../../../components/ui/TablePrimitives";
import { PanelSurface } from "../../../../components/ui/PanelSurface";
import { TablePagination } from "../../../../components/ui/TablePagination";

import { Button } from "../../../../components/Button";
import { CodeBlock } from "../../../../components/CodeBlock";
import { Field, TextInput } from "../../../../components/Field";
import { StatusBanner } from "../../../../components/StatusBanner";
import { useI18n } from "../../../../i18n/I18nProvider";
import { apiRequest } from "../../../../lib/api";
import type { ExpandedGrantItem, QueryTestResult } from "../../../../lib/domain";

type QueryTestGroup = { key?: string; name?: string; source?: string; snapshot_version?: string };
type QueryTestGrant = Partial<ExpandedGrantItem> & {
  permission?: string;
  scope?: string;
  source_type?: string;
  source_key?: string;
  name?: string;
  snapshot_version?: string;
  grant_type?: string;
};
type StructuredQueryTestResult = QueryTestResult & {
  source?: string;
  snapshot_version?: string;
  groups?: QueryTestGroup[];
  grants?: QueryTestGrant[];
};

export function QueryTestTab({ appKey }: { appKey: string }) {
  const { t } = useI18n();
  const [userId, setUserId] = useState("");
  const [token, setToken] = useState("");
  const [result, setResult] = useState<StructuredQueryTestResult | null>(null);
  const testMutation = useMutation({
    mutationFn: () =>
      apiRequest<StructuredQueryTestResult>(`/console/api/v1/apps/${appKey}/permission-query-tests`, {
        method: "POST",
        body: { user_id: userId, token },
      }),
    onSuccess: (payload) => {
      setResult(payload);
      setToken("");
    },
  });
  const groupColumns: ColumnDef<QueryTestGroup>[] = [
    { header: t("console.queryTest.column.group"), cell: ({ row }) => row.original.key ?? "-" },
    { header: t("common.name"), cell: ({ row }) => row.original.name ?? "-" },
    { header: t("common.source"), cell: ({ row }) => row.original.source ?? "-" },
    { header: t("wizard.verify.snapshotVersion"), cell: ({ row }) => row.original.snapshot_version ?? result?.snapshot_version ?? "-" },
  ];
  const grantColumns: ColumnDef<QueryTestGrant>[] = [
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
    { header: t("wizard.verify.snapshotVersion"), cell: ({ row }) => row.original.snapshot_version ?? result?.snapshot_version ?? "-" },
  ];
  const groupTable = useReactTable({
    data: result?.groups ?? [],
    columns: groupColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });
  const grantTable = useReactTable({
    data: result?.grants ?? [],
    columns: grantColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  });

  return (
    <section className="space-y-6">
      <PanelSurface padding="lg" className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]">
        <Field label={t("wizard.verify.userId")}>
          <TextInput value={userId} onChange={(event) => setUserId(event.currentTarget.value)} />
        </Field>
        <Field label="Bearer token">
          <TextInput type="password" value={token} onChange={(event) => setToken(event.currentTarget.value)} autoComplete="off" />
        </Field>
        <Button variant="primary" icon={<Play size={16} />} disabled={!userId || !token} onClick={() => testMutation.mutate()}>
          {t("wizard.verify.run")}
        </Button>
      </PanelSurface>
      {testMutation.error ? <StatusBanner tone="signal" title={t("wizard.verify.failed")} message={(testMutation.error as Error).message} /> : null}
      {result ? (
        <>
          <StatusBanner
            tone={result.allowed ? "evergreen" : "neutral"}
            title={result.allowed ? t("wizard.verify.hit") : t("wizard.verify.noHit")}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <PanelSurface>
              <span className="text-xs font-semibold text-ink-faint">{t("common.source")}</span>
              <strong className="mt-2 block text-sm font-semibold text-ink">{result.source ?? "-"}</strong>
            </PanelSurface>
            <PanelSurface>
              <span className="text-xs font-semibold text-ink-faint">{t("wizard.verify.snapshotVersion")}</span>
              <strong className="mt-2 block text-sm font-semibold text-ink">{result.snapshot_version ?? "-"}</strong>
            </PanelSurface>
          </div>
          <TableFrame>
            <TableRoot>
              <TableHead>
                {groupTable.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
                    ))}
                  </TableRow>
                ))}
              </TableHead>
              <TableBody>
                {groupTable.getRowModel().rows.length > 0 ? (
                  groupTable.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={groupColumns.length}>
                      {t("console.queryTest.groupsEmpty")}
                    </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={groupTable} totalItems={result.groups?.length ?? 0} />
          </TableFrame>
          <TableFrame>
            <TableRoot>
              <TableHead>
                {grantTable.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHeaderCell key={header.id}>{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHeaderCell>
                    ))}
                  </TableRow>
                ))}
              </TableHead>
              <TableBody>
                {grantTable.getRowModel().rows.length > 0 ? (
                  grantTable.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmptyRow colSpan={grantColumns.length}>
                      {t("console.queryTest.grantsEmpty")}
                    </TableEmptyRow>
                )}
              </TableBody>
            </TableRoot>
            <TablePagination table={grantTable} totalItems={result.grants?.length ?? 0} />
          </TableFrame>
          <CodeBlock language="json" code={JSON.stringify(result, null, 2)} />
        </>
      ) : null}
    </section>
  );
}
